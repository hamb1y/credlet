#!/usr/bin/env python3
"""Build the disposable native acceptance APK using the pinned SDK and a JDK (no Gradle)."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-home', type=Path, required=True)
    args = parser.parse_args()
    java = args.java_home.resolve() / 'bin'
    sdk = ROOT / '.tools/android-sdk'
    build = sdk / 'build-tools/35.0.0'
    android = sdk / 'platforms/android-35/android.jar'
    output = ROOT / '.tools/android-test/fixture'
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'JAVA_HOME': str(java.parent), 'PATH': str(java) + os.pathsep + os.environ['PATH']}

    def run(command):
        subprocess.run(list(map(str, command)), check=True, env=env, capture_output=True)

    with tempfile.TemporaryDirectory(prefix='lockbox-apk-') as tmp:
        work = Path(tmp)
        classes = work / 'classes'; classes.mkdir()
        dex = work / 'dex'; dex.mkdir()
        source = ROOT / 'tests/android'
        run([java/'javac', '-source', '17', '-target', '17', '-classpath', android,
             '-d', classes, *sorted(source.glob('*.java'))])
        run([build/'d8', '--lib', android, '--min-api', '34', '--output', dex, *classes.rglob('*.class')])
        unsigned = work/'unsigned.apk'
        run([build/'aapt2', 'link', '-I', android, '--manifest', source/'AndroidManifest.xml', '-o', unsigned])
        with zipfile.ZipFile(unsigned, 'a') as archive:
            archive.write(dex/'classes.dex', 'classes.dex')
        aligned = work/'aligned.apk'
        run([build/'zipalign', '-f', '4', unsigned, aligned])
        keystore = output/'fixture.p12'
        if not keystore.exists():
            run([java/'keytool', '-genkeypair', '-keystore', keystore, '-storepass', 'fixture-only',
                 '-alias', 'fixture', '-keyalg', 'RSA', '-keysize', '2048', '-validity', '3650',
                 '-dname', 'CN=Disposable Lockbox acceptance'])
            keystore.chmod(0o600)
        apk = output/'lockbox-fixture.apk'
        run([build/'apksigner', 'sign', '--ks', keystore, '--ks-pass', 'pass:fixture-only',
             '--out', apk, aligned])
        run([build/'apksigner', 'verify', apk])
        print(apk)


if __name__ == '__main__': main()
