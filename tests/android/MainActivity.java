package org.credlet.fixture;

import android.app.Activity;
import android.content.ClipboardManager;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.view.autofill.AutofillManager;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;

/** Disposable native relying app. Only fixture data is written, in its private sandbox. */
public class MainActivity extends Activity {
    private EditText username, password, code;
    private TextView status;

    private EditText field(LinearLayout layout, String hint, int type, String autofillHint) {
        EditText field = new EditText(this);
        field.setId(View.generateViewId());
        field.setHint(hint);
        field.setContentDescription(hint);
        field.setInputType(type);
        field.setAutofillHints(autofillHint);
        field.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_YES);
        layout.addView(field);
        return field;
    }

    private void button(LinearLayout layout, String text, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(text);
        button.setOnClickListener(listener);
        layout.addView(button);
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(24, 48, 24, 24);
        TextView title = new TextView(this);
        title.setText("Native Credlet acceptance fixture");
        layout.addView(title);
        username = field(layout, "Fixture username", InputType.TYPE_CLASS_TEXT, View.AUTOFILL_HINT_USERNAME);
        password = field(layout, "Fixture password", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD, View.AUTOFILL_HINT_PASSWORD);
        code = field(layout, "Fixture code", InputType.TYPE_CLASS_NUMBER, "smsOTPCode");
        button(layout, "Request autofill", view -> {
            getSystemService(ClipboardManager.class).clearPrimaryClip();
            username.requestFocus();
            getSystemService(InputMethodManager.class).showSoftInput(username, InputMethodManager.SHOW_IMPLICIT);
            getSystemService(AutofillManager.class).requestAutofill(username);
        });
        button(layout, "Paste code", view -> {
            ClipboardManager clipboard = getSystemService(ClipboardManager.class);
            if (clipboard.hasPrimaryClip()) {
                code.setText(clipboard.getPrimaryClip().getItemAt(0).coerceToText(this));
                clipboard.clearPrimaryClip();
            }
        });
        status = new TextView(this);
        button(layout, "Inspect fields", view -> {
            try {
                JSONObject result = new JSONObject();
                result.put("username", username.getText().toString());
                result.put("password", password.getText().toString());
                result.put("code", code.getText().toString());
                try (java.io.FileOutputStream out = openFileOutput("fields.json", MODE_PRIVATE)) {
                    out.write(result.toString().getBytes(StandardCharsets.UTF_8));
                }
                status.setText("Fixture fields inspected");
            } catch (Exception error) { status.setText(error.getClass().getSimpleName()); }
        });
        layout.addView(status);
        setContentView(layout);
    }
}
