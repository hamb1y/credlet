(() => {
  if (globalThis.__lockboxContent) return;
  globalThis.__lockboxContent = true;
  const api = globalThis.browser || globalThis.chrome;
  const visible = field => field instanceof HTMLInputElement && !field.disabled && !field.readOnly &&
    field.type !== 'hidden' && field.getClientRects().length > 0 &&
    getComputedStyle(field).visibility !== 'hidden' && getComputedStyle(field).display !== 'none';
  const setValue = (field, value) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(field, value);
    field.dispatchEvent(new Event('input', {bubbles: true}));
    field.dispatchEvent(new Event('change', {bubbles: true}));
  };
  api.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== api.runtime.id || !['lockbox-fill','lockbox-fill-code'].includes(message.type)) return false;
    if (location.protocol !== 'https:' || location.origin !== message.origin || window.top !== window) {
      respond({filled: false}); return false;
    }
    const fields = [...document.querySelectorAll('input')].filter(visible);
    const active = document.activeElement;
    if (message.type === 'lockbox-fill-code') {
      const codes=fields.filter(f=>['text','tel','number'].includes(f.type) &&
        (f.autocomplete === 'one-time-code' || /^(otp|totp|code|verification.?code|authenticator.?code)$/i.test(f.name || f.id)));
      const field=codes.includes(active) ? active : codes.length===1 ? codes[0] : null;
      if (!field || (field.form && new URL(field.form.action || location.href,location.href).origin !== location.origin)) {
        respond({filled:false});return false;
      }
      setValue(field,message.code);respond({filled:true});return false;
    }
    const passwords = fields.filter(f => f.type === 'password');
    // Prefer the focused form, otherwise one unambiguous login form.
    const password = passwords.find(f => f.form && f.form === active?.form) ||
      (passwords.length === 1 ? passwords[0] : null);
    const scope = password?.form ? fields.filter(f => f.form === password.form) : fields;
    const candidates = scope.filter(f => ['text', 'email', 'tel'].includes(f.type) &&
      (f.autocomplete === 'username' || f.type === 'email' || /user|email|login/i.test(f.name + ' ' + f.id)));
    const username = candidates.length === 1 ? candidates[0] : candidates.find(f => f.autocomplete === 'username');
    // Reject forms which submit credentials to a different origin or downgrade to HTTP.
    for (const field of [password, username].filter(Boolean)) {
      if (field.form && new URL(field.form.action || location.href, location.href).origin !== location.origin) {
        respond({filled: false}); return false;
      }
    }
    if (username) setValue(username, message.username || '');
    if (password) setValue(password, message.password || '');
    respond({filled: !!(username || password)});
    return false; // Never submit the form automatically.
  });
})();
