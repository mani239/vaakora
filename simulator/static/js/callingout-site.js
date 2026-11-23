/* Vaakora Public Marketing & Shared UI Interactions */
(function () {
  'use strict';

  function initHeaderNav() {
    var trigger = document.getElementById('mobileMenuTrigger');
    var sheet = document.getElementById('mobileMenuSheet');
    var closeBtn = document.getElementById('mobileMenuClose');
    if (trigger && sheet && closeBtn) {
      function openSheet() {
        sheet.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        closeBtn.focus();
      }
      function closeSheet() {
        sheet.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        trigger.focus();
      }
      trigger.addEventListener('click', openSheet);
      closeBtn.addEventListener('click', closeSheet);
      sheet.querySelectorAll('a').forEach(function (link) {
        link.addEventListener('click', function () {
          sheet.hidden = true;
          trigger.setAttribute('aria-expanded', 'false');
        });
      });
      document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape' && !sheet.hidden) closeSheet();
      });
    }

    document.querySelectorAll('[data-dropdown-trigger]').forEach(function (btn) {
      var menuId = btn.getAttribute('aria-controls');
      var menu = menuId ? document.getElementById(menuId) : null;
      if (!menu) return;
      btn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var nextOpen = menu.hidden;
        document.querySelectorAll('.site-nav__menu').forEach(function (m) {
          m.hidden = true;
        });
        document.querySelectorAll('[data-dropdown-trigger]').forEach(function (b) {
          b.setAttribute('aria-expanded', 'false');
        });
        menu.hidden = !nextOpen;
        btn.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
      });
    });

    document.addEventListener('click', function () {
      document.querySelectorAll('.site-nav__menu').forEach(function (m) {
        m.hidden = true;
      });
      document.querySelectorAll('[data-dropdown-trigger]').forEach(function (b) {
        b.setAttribute('aria-expanded', 'false');
      });
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') {
        document.querySelectorAll('.site-nav__menu').forEach(function (m) {
          m.hidden = true;
        });
        document.querySelectorAll('[data-dropdown-trigger]').forEach(function (b) {
          b.setAttribute('aria-expanded', 'false');
        });
      }
    });
  }

  function initHeroCallStrip() {
    var strip = document.getElementById('heroCallStrip');
    var playBtn = document.getElementById('heroStripPlayBtn');
    var progressFill = document.getElementById('heroStripProgress');
    var statusLabel = document.getElementById('heroStripStatus');
    if (!strip || !playBtn) return;

    var audio = null;
    var lanes = strip.querySelectorAll('.call-lane');
    var playSrc = strip.getAttribute('data-audio-src') || '/static/previews/hero-archie-call.wav';

    function resetVisuals(labelText) {
      strip.classList.remove('is-playing');
      playBtn.setAttribute('aria-pressed', 'false');
      playBtn.textContent = 'Play Archie sample';
      if (progressFill) progressFill.style.width = '0%';
      lanes.forEach(function (el) { el.classList.remove('is-active'); });
      if (statusLabel && labelText) statusLabel.textContent = labelText;
    }

    playBtn.addEventListener('click', function () {
      if (audio && !audio.paused) {
        audio.pause();
        audio.currentTime = 0;
        resetVisuals('Paused');
        return;
      }
      if (window.__callingOutActiveAudio && window.__callingOutActiveAudio !== audio) {
        window.__callingOutActiveAudio.pause();
      }
      if (!audio) {
        audio = new Audio(playSrc);
        audio.addEventListener('timeupdate', function () {
          if (!audio.duration) return;
          var ratio = Math.min(1, audio.currentTime / audio.duration);
          if (progressFill) progressFill.style.width = (ratio * 100).toFixed(1) + '%';
          var activeIdx = ratio < 0.35 ? 0 : (ratio < 0.55 ? 1 : 2);
          lanes.forEach(function (el, idx) {
            el.classList.toggle('is-active', idx === activeIdx);
          });
        });
        audio.addEventListener('ended', function () {
          resetVisuals('Finished sample playback');
        });
        audio.addEventListener('error', function () {
          resetVisuals('Audio failed to load. Click Play to retry.');
        });
      }
      window.__callingOutActiveAudio = audio;
      playBtn.textContent = 'Loading audio...';
      audio.play().then(function () {
        strip.classList.add('is-playing');
        playBtn.setAttribute('aria-pressed', 'true');
        playBtn.textContent = 'Stop sample';
        if (statusLabel) statusLabel.textContent = 'Playing recorded agent turn';
      }).catch(function () {
        resetVisuals('Could not play audio. Check browser audio settings and retry.');
      });
    });

    var metricsToggle = document.getElementById('heroMetricsToggle');
    if (metricsToggle) {
      metricsToggle.addEventListener('click', function () {
        var expanded = metricsToggle.getAttribute('aria-expanded') === 'true';
        var next = !expanded;
        metricsToggle.setAttribute('aria-expanded', next ? 'true' : 'false');
        metricsToggle.textContent = next ? 'Hide engine details' : 'Show engine details';
        strip.querySelectorAll('.call-lane__meta--hidden').forEach(function (m) {
          m.hidden = !next;
        });
      });
    }
  }

  function initVoicePreviewButtons() {
    var activeBtn = null;
    var activeAudio = null;

    function resetBtn(btn, stateText) {
      if (!btn) return;
      btn.setAttribute('aria-pressed', 'false');
      var idleLabel = btn.getAttribute('data-idle-label') || 'Play sample';
      btn.textContent = idleLabel;
      var statusId = btn.getAttribute('data-status-target');
      if (statusId && stateText !== undefined) {
        var st = document.getElementById(statusId);
        if (st) st.textContent = stateText;
      }
    }

    document.querySelectorAll('[data-voice-play]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var key = btn.getAttribute('data-voice-play');
        var src = btn.getAttribute('data-audio-src') || ('/static/previews/personas/' + encodeURIComponent(key) + '.wav');
        var statusId = btn.getAttribute('data-status-target');
        var statusEl = statusId ? document.getElementById(statusId) : null;

        if (activeBtn === btn && activeAudio && !activeAudio.paused) {
          activeAudio.pause();
          activeAudio.currentTime = 0;
          resetBtn(btn, '');
          activeBtn = null;
          return;
        }
        if (activeAudio) {
          activeAudio.pause();
          resetBtn(activeBtn, '');
        }
        if (window.__callingOutActiveAudio && window.__callingOutActiveAudio !== activeAudio) {
          window.__callingOutActiveAudio.pause();
        }

        btn.textContent = 'Loading...';
        if (statusEl) statusEl.textContent = 'Loading voice sample...';

        var audio = new Audio(src);
        activeAudio = audio;
        activeBtn = btn;
        window.__callingOutActiveAudio = audio;

        audio.addEventListener('ended', function () {
          resetBtn(btn, '');
          if (activeBtn === btn) activeBtn = null;
        });

        audio.addEventListener('error', function () {
          fetch('/api/voice/preview?speaker=' + encodeURIComponent(key))
            .then(function (r) { return r.json(); })
            .then(function (d) {
              if (!d || !d.audio) throw new Error('No audio');
              var fb = new Audio('data:audio/wav;base64,' + d.audio);
              activeAudio = fb;
              window.__callingOutActiveAudio = fb;
              fb.addEventListener('ended', function () {
                resetBtn(btn, '');
                if (activeBtn === btn) activeBtn = null;
              });
              return fb.play();
            })
            .then(function () {
              btn.setAttribute('aria-pressed', 'true');
              btn.textContent = 'Stop';
              if (statusEl) statusEl.textContent = 'Playing sample';
            })
            .catch(function () {
              resetBtn(btn, 'Sample failed to load. Click Play sample to try again.');
              if (activeBtn === btn) activeBtn = null;
            });
        });

        audio.play().then(function () {
          btn.setAttribute('aria-pressed', 'true');
          btn.textContent = 'Stop';
          if (statusEl) statusEl.textContent = 'Playing sample';
        }).catch(function () {
          /* handled by error listener if load failed */
        });
      });
    });
  }

  function initPricingControls() {
    var fmtInr = new Intl.NumberFormat('en-IN');
    var callsRange = document.getElementById('calcCallsDay');
    var minsRange = document.getElementById('calcAvgMins');
    var daysSelect = document.getElementById('calcDaysMonth');
    var outMins = document.getElementById('calcMonthlyMins');
    var outCost = document.getElementById('calcEstCost');
    var outPlan = document.getElementById('calcRecPlan');

    function recompute() {
      if (!callsRange || !minsRange) return;
      var calls = Number(callsRange.value || 100);
      var mins = Number(minsRange.value || 2);
      var days = Number(daysSelect ? daysSelect.value : 25);
      var callsLabel = document.getElementById('calcCallsDayValue');
      var minsLabel = document.getElementById('calcAvgMinsValue');
      if (callsLabel) callsLabel.textContent = fmtInr.format(calls) + ' calls/day';
      if (minsLabel) minsLabel.textContent = mins.toFixed(1) + ' min avg';

      var totalMins = Math.round(calls * mins * days);
      var planName = 'Starter';
      var estCost = 4999;

      if (totalMins <= 1000) {
        planName = 'Starter (1,000 included min)';
        estCost = 4999;
      } else if (totalMins <= 5200) {
        var extra = Math.max(0, totalMins - 3500);
        if (totalMins <= 2200) {
          planName = 'Starter + overage at Rs 5.50/min';
          estCost = 4999 + Math.round((totalMins - 1000) * 5.5);
        } else {
          planName = 'Growth (3,500 included min)';
          estCost = 14999 + Math.round(extra * 4.75);
        }
      } else {
        planName = 'Scale (custom from Rs 3.50/min)';
        estCost = Math.round(totalMins * 3.5);
      }

      if (outMins) outMins.textContent = fmtInr.format(totalMins) + ' min/month';
      if (outCost) outCost.textContent = '\u20B9' + fmtInr.format(estCost) + ' / mo + GST';
      if (outPlan) outPlan.textContent = planName;
    }

    if (callsRange && minsRange) {
      callsRange.addEventListener('input', recompute);
      minsRange.addEventListener('input', recompute);
      if (daysSelect) daysSelect.addEventListener('change', recompute);
      recompute();
    }

    var billingBtns = document.querySelectorAll('[data-billing-cycle]');
    if (billingBtns.length) {
      billingBtns.forEach(function (b) {
        b.addEventListener('click', function () {
          var mode = b.getAttribute('data-billing-cycle');
          billingBtns.forEach(function (other) {
            other.setAttribute('aria-pressed', other === b ? 'true' : 'false');
          });
          document.querySelectorAll('[data-price-monthly]').forEach(function (el) {
            var monthly = el.getAttribute('data-price-monthly');
            var annual = el.getAttribute('data-price-annual');
            el.textContent = mode === 'annual' ? annual : monthly;
          });
          document.querySelectorAll('[data-billing-note]').forEach(function (note) {
            note.textContent = mode === 'annual' ? 'Billed annually (15% off)' : 'Billed monthly, excl. 18% GST';
          });
        });
      });
    }
  }

  function initVoiceDirectoryFilters() {
    var cards = document.querySelectorAll('[data-voice-card]');
    if (!cards.length) return;
    var activeGender = 'all';
    var activeUse = 'all';
    var emptyEl = document.getElementById('voiceFilterEmpty');

    function applyFilters() {
      var shown = 0;
      cards.forEach(function (card) {
        var g = card.getAttribute('data-gender') || '';
        var u = card.getAttribute('data-use') || '';
        var matchG = activeGender === 'all' || g === activeGender;
        var matchU = activeUse === 'all' || u === activeUse;
        var visible = matchG && matchU;
        card.hidden = !visible;
        if (visible) shown++;
      });
      if (emptyEl) emptyEl.hidden = shown > 0;
    }

    document.querySelectorAll('[data-filter-gender]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        activeGender = btn.getAttribute('data-filter-gender') || 'all';
        document.querySelectorAll('[data-filter-gender]').forEach(function (b) {
          b.setAttribute('aria-pressed', b === btn ? 'true' : 'false');
        });
        applyFilters();
      });
    });

    document.querySelectorAll('[data-filter-use]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        activeUse = btn.getAttribute('data-filter-use') || 'all';
        document.querySelectorAll('[data-filter-use]').forEach(function (b) {
          b.setAttribute('aria-pressed', b === btn ? 'true' : 'false');
        });
        applyFilters();
      });
    });
  }

  function initHomeShowcaseToggle() {
    var toggle = document.getElementById('showcaseMetricsToggle');
    var panel = document.getElementById('consoleShowcase');
    if (!toggle || !panel) return;
    toggle.addEventListener('click', function () {
      var expanded = toggle.getAttribute('aria-expanded') === 'true';
      var next = !expanded;
      toggle.setAttribute('aria-expanded', next ? 'true' : 'false');
      toggle.textContent = next ? 'Hide engine details' : 'Show engine details';
      panel.querySelectorAll('.call-lane__meta--hidden').forEach(function (m) {
        m.hidden = !next;
      });
    });
  }

  function initContactForm() {
    var form = document.getElementById('trustContactForm');
    if (!form) return;
    var statusBox = document.getElementById('contactFormStatus');
    var submitBtn = document.getElementById('contactSubmitBtn');

    function setErr(id, msg) {
      var el = document.getElementById(id);
      if (!el) return;
      el.textContent = msg || '';
      el.hidden = !msg;
    }

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var name = (document.getElementById('contactName').value || '').trim();
      var email = (document.getElementById('contactEmail').value || '').trim();
      var phone = (document.getElementById('contactPhone').value || '').trim();
      var company = (document.getElementById('contactCompany').value || '').trim();
      var leadsPerDay = (document.getElementById('contactLeadsPerDay').value || '').trim();
      var message = (document.getElementById('contactMessage').value || '').trim();

      var valid = true;
      setErr('contactNameErr', '');
      setErr('contactEmailErr', '');

      if (!name) {
        setErr('contactNameErr', 'Enter your full name.');
        valid = false;
      }
      if (!email || email.indexOf('@') === -1 || email.split('@')[1].indexOf('.') === -1) {
        setErr('contactEmailErr', 'Enter a valid work email address.');
        valid = false;
      }
      if (!valid) return;

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Sending...';
      }
      if (statusBox) {
        statusBox.hidden = true;
        statusBox.className = 'notice-box';
      }

      fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name,
          email: email,
          phone: phone,
          company: company,
          leads_per_day: leadsPerDay,
          message: message
        })
      })
        .then(function (r) {
          return r.json().then(function (data) { return { ok: r.ok, data: data }; });
        })
        .then(function (res) {
          if (!res.ok) throw new Error((res.data && res.data.error) || 'Could not submit inquiry.');
          form.reset();
          if (statusBox) {
            statusBox.hidden = false;
            statusBox.className = 'notice-box notice-box--ok';
            statusBox.textContent = res.data.message || 'Inquiry received. Our Hyderabad team will reply within one business day.';
          }
        })
        .catch(function (err) {
          if (statusBox) {
            statusBox.hidden = false;
            statusBox.className = 'notice-box notice-box--error';
            statusBox.textContent = (err && err.message ? err.message : 'Request failed.') + ' Email grievance@vaakora.in if the error continues.';
          }
        })
        .finally(function () {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Send inquiry';
          }
        });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initHeaderNav();
    initHeroCallStrip();
    initVoicePreviewButtons();
    initPricingControls();
    initVoiceDirectoryFilters();
    initHomeShowcaseToggle();
    initContactForm();
  });
})();
