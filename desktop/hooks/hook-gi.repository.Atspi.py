"""Collect AT-SPI's typelib and its shared-library dependencies for Linux bundles."""
from PyInstaller.utils.hooks.gi import GiModuleInfo


def hook(hook_api):
    module = GiModuleInfo('Atspi', '2.0')
    if not module.available:
        raise RuntimeError('The AT-SPI 2 typelib is required to build Lockbox.')
    binaries, data, imports = module.collect_typelib_data()
    hook_api.add_binaries(binaries)
    hook_api.add_datas(data)
    hook_api.add_imports(*imports)
