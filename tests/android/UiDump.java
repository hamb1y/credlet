package org.credlet.fixture;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.UiAutomation;
import android.graphics.Rect;
import android.os.HandlerThread;
import android.os.Looper;
import android.util.Xml;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import org.xmlpull.v1.XmlSerializer;
import java.util.List;
import java.util.Locale;

/** Shell-only test helper: include keyboard/provider windows omitted by uiautomator dump. */
public final class UiDump {
    private static int remaining = 10000;

    private static boolean click(AccessibilityNodeInfo node, String label, int depth) {
        if (node == null || depth > 50 || remaining-- <= 0) return false;
        if (node.isVisibleToUser() && (label.contentEquals(node.getText() == null ? "" : node.getText().toString().toLowerCase(Locale.ROOT))
                || label.contentEquals(node.getContentDescription() == null ? "" : node.getContentDescription().toString().toLowerCase(Locale.ROOT)))) {
            AccessibilityNodeInfo target = node;
            for (int parents = 0; target != null && parents < 8; parents++, target = target.getParent())
                if (target.isVisibleToUser() && target.isEnabled()
                        && target.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true;
        }
        for (int i = 0; i < node.getChildCount(); i++)
            if (click(node.getChild(i), label, depth + 1)) return true;
        return false;
    }

    private static void dump(XmlSerializer xml, AccessibilityNodeInfo node, int depth) throws Exception {
        if (node == null || depth > 50 || remaining-- <= 0) return;
        xml.startTag(null, "node");
        String[] names = {"text", "content-desc", "class", "package", "resource-id"};
        CharSequence[] values = {node.getText(), node.getContentDescription(), node.getClassName(),
            node.getPackageName(), node.getViewIdResourceName()};
        for (int i = 0; i < names.length; i++)
            xml.attribute(null, names[i], values[i] == null ? "" : values[i].toString());
        Rect bounds = new Rect(); node.getBoundsInScreen(bounds);
        xml.attribute(null, "bounds", bounds.toShortString());
        xml.attribute(null, "password", Boolean.toString(node.isPassword()));
        xml.attribute(null, "clickable", Boolean.toString(node.isClickable()));
        xml.attribute(null, "enabled", Boolean.toString(node.isEnabled()));
        xml.attribute(null, "visible", Boolean.toString(node.isVisibleToUser()));
        for (int i = 0; i < node.getChildCount(); i++) dump(xml, node.getChild(i), depth + 1);
        xml.endTag(null, "node");
    }

    public static void main(String[] args) throws Exception {
        Looper.prepareMainLooper();
        HandlerThread thread = new HandlerThread("credlet-ui-dump"); thread.start();
        Class<?> connectionType = Class.forName("android.app.IUiAutomationConnection");
        Object connection = Class.forName("android.app.UiAutomationConnection").getConstructor().newInstance();
        UiAutomation automation = (UiAutomation) UiAutomation.class
            .getConstructor(Looper.class, connectionType).newInstance(thread.getLooper(), connection);
        try {
            UiAutomation.class.getMethod("connect").invoke(automation);
            AccessibilityServiceInfo info = automation.getServiceInfo();
            info.flags |= AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
                | AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS;
            automation.setServiceInfo(info);
            try { automation.waitForIdle(200, 2000); } catch (java.util.concurrent.TimeoutException ignored) { }
            List<AccessibilityWindowInfo> windows = automation.getWindows();
            for (int retry = 0; retry < 20; retry++) {
                boolean application = false;
                for (AccessibilityWindowInfo window : windows)
                    if (window.getType() == AccessibilityWindowInfo.TYPE_APPLICATION && window.getRoot() != null) application = true;
                if (application) break;
                Thread.sleep(100); windows = automation.getWindows();
            }
            if (windows.isEmpty()) throw new IllegalStateException("No accessible windows");
            if (args.length == 2 && args[0].equals("--click")) {
                boolean clicked = false;
                for (AccessibilityWindowInfo window : windows)
                    if (click(window.getRoot(), args[1].toLowerCase(Locale.ROOT), 0)) { clicked = true; break; }
                System.out.print("<action success=\"" + clicked + "\" />");
                return;
            }
            XmlSerializer xml = Xml.newSerializer(); xml.setOutput(System.out, "UTF-8");
            xml.startDocument("UTF-8", true); xml.startTag(null, "hierarchy");
            for (AccessibilityWindowInfo window : windows) dump(xml, window.getRoot(), 0);
            xml.endTag(null, "hierarchy"); xml.endDocument();
        } finally {
            UiAutomation.class.getMethod("disconnect").invoke(automation);
            thread.quitSafely();
        }
    }
}
