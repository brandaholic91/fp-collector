(function () {
  const COLLECTOR_URL = '/v1/events';
  const CONSENT_KEY = 'consent_analytics';
  const ANON_KEY = 'anonymous_id';

  function getOrCreate(storage, key, factory) {
    let val = storage.getItem(key);
    if (!val) { val = factory(); storage.setItem(key, val); }
    return val;
  }

  function uuidv4() {
    return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
      (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
    );
  }

  function getUtmParams() {
    const p = new URLSearchParams(window.location.search);
    return {
      utm_source:   p.get('utm_source')   || null,
      utm_medium:   p.get('utm_medium')   || null,
      utm_campaign: p.get('utm_campaign') || null,
      utm_term:     p.get('utm_term')     || null,
      utm_content:  p.get('utm_content')  || null,
      fbclid:       p.get('fbclid')       || null,
    };
  }

  function hasConsent() {
    return localStorage.getItem(CONSENT_KEY) === 'true';
  }

  window.track = function (eventName, payload = {}) {
    if (!hasConsent()) return;
    fetch(COLLECTOR_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_id:          uuidv4(),
        event_name:        eventName,
        occurred_at:       new Date().toISOString(),
        session_id:        getOrCreate(sessionStorage, 'session_id', uuidv4),
        anonymous_id:      getOrCreate(localStorage, ANON_KEY, uuidv4),
        page_url:          window.location.href,
        referrer:          document.referrer || null,
        consent_analytics: true,
        payload:           payload,
        ...getUtmParams(),
      }),
    }).catch(() => {});
  };

  window.grantConsent = function () {
    localStorage.setItem(CONSENT_KEY, 'true');
    track('page_view');
  };

  if (hasConsent()) {
    track('page_view');
  }
})();
