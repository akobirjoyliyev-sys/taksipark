/* Kassa — Telegram Web App. Server matnlari faqat textContent orqali chiqariladi (XSS yo‘q). */
(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp;
  const app = document.getElementById("app");
  const tabs = document.getElementById("tabs");
  const toastEl = document.getElementById("toast");
  const QUICK = [10000, 50000, 100000, 200000, 500000];

  let me = null;
  let pollTimer = null;
  let tickTimer = null;
  const backStack = [];

  // ------------------------------------------------------------------ yordamchilar
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  const fmt = (n) => Math.round(Number(n)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ") + " so‘m";
  const digits = (s) => String(s || "").replace(/\D/g, "");
  const pct = (s) => String(Number(s || 0));

  function haptic(type) {
    try {
      if (!tg || !tg.HapticFeedback) return;
      if (type === "ok" || type === "error" || type === "warning") tg.HapticFeedback.notificationOccurred(type === "ok" ? "success" : type);
      else tg.HapticFeedback.impactOccurred("light");
    } catch (_) { /* eski klient */ }
  }

  function toast(text, kind) {
    toastEl.textContent = text;
    toastEl.className = "toast " + (kind || "");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.add("hidden"), 3600);
    haptic(kind === "err" ? "error" : kind === "ok" ? "ok" : "tap");
  }

  async function copy(text, label) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      const ta = h("textarea", {}, text);
      document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
    }
    toast((label || "Nusxa olindi") + " ✅", "ok");
  }

  async function api(method, path, body) {
    const res = await fetch("/api/webapp" + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": (tg && tg.initData) || "",
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch (_) { /* bo‘sh javob */ }
    if (!res.ok) {
      const err = new Error(data.error || "Xatolik yuz berdi. Qayta urinib ko‘ring.");
      err.status = res.status; err.data = data;
      throw err;
    }
    return data;
  }

  async function withBusy(btn, fn) {
    if (btn) { btn.disabled = true; btn._label = btn.textContent; btn.textContent = "⏳ Kuting..."; }
    try { return await fn(); }
    catch (e) { toast(e.message, "err"); if (e.data && e.data.gate) renderGate(e.data.gate); return null; }
    finally { if (btn && btn.isConnected) { btn.disabled = false; btn.textContent = btn._label; } }
  }

  function stopTimers() { clearInterval(pollTimer); clearInterval(tickTimer); pollTimer = tickTimer = null; }

  function screen(...nodes) {
    stopTimers();
    app.replaceChildren(h("div", { class: "fade" }, ...nodes));
    window.scrollTo(0, 0);
  }

  // ------------------------------------------------------------------ navigatsiya
  function setTab(name) {
    for (const b of tabs.querySelectorAll(".tab")) b.classList.toggle("active", b.dataset.tab === name);
  }

  function go(render, ...args) {
    backStack.push([render, args]);
    updateBack();
    render(...args);
  }

  function root(tab) {
    backStack.length = 0;
    updateBack();
    setTab(tab);
    ({ home: renderHome, deposit: startDeposit, withdraw: startWithdraw, history: renderHistory, bonus: renderBonus })[tab]();
  }

  function back() {
    backStack.pop();
    const prev = backStack[backStack.length - 1];
    updateBack();
    if (prev) prev[0](...prev[1]); else root("home");
  }

  function updateBack() {
    if (!tg || !tg.BackButton) return;
    if (backStack.length > 0) tg.BackButton.show(); else tg.BackButton.hide();
  }

  tabs.addEventListener("click", (e) => {
    const b = e.target.closest(".tab");
    if (!b) return;
    haptic("tap");
    root(b.dataset.tab);
  });

  // ------------------------------------------------------------------ yuklash
  async function load() {
    me = await api("GET", "/me");
    return me;
  }

  async function boot() {
    if (tg) {
      tg.ready(); tg.expand();
      try { tg.setHeaderColor("secondary_bg_color"); } catch (_) { /* eski klient */ }
      if (tg.BackButton) tg.BackButton.onClick(back);
    }
    if (!tg || !tg.initData) {
      screen(h("div", { class: "empty" }, h("div", { class: "e" }, "🔒"),
        h("h1", {}, "Ilovani Telegram ichida oching"),
        h("p", {}, "Bu sahifa faqat bot ichidagi «💳 Kassa» tugmasi orqali ishlaydi.")));
      return;
    }
    try { await load(); }
    catch (e) {
      screen(h("div", { class: "empty" }, h("div", { class: "e" }, "⚠️"), h("p", {}, e.message),
        h("button", { class: "btn", onclick: () => location.reload() }, "🔄 Qayta urinish")));
      return;
    }
    if (me.gate) { renderGate(me.gate); return; }
    tabs.classList.remove("hidden");
    root("home");
  }

  function renderGate(gate) {
    tabs.classList.add("hidden");
    const items = (gate.channels || []).map((c) =>
      h("button", { class: "item", onclick: () => (tg ? tg.openTelegramLink(c.url) : open(c.url)) },
        h("div", { class: "ic" }, "📢"), h("div", { class: "main" }, h("div", { class: "title" }, c.title)),
        h("span", { class: "chev" }, "›")));
    screen(
      h("div", { class: "empty" }, h("div", { class: "e" }, gate.type === "contact" ? "📱" : "📢"), h("p", {}, gate.message)),
      items.length ? h("div", { class: "list" }, items) : null,
      h("button", { class: "btn", onclick: async (e) => {
        await withBusy(e.currentTarget, load);
        if (me && !me.gate) { tabs.classList.remove("hidden"); root("home"); }
        else toast("Hali tayyor emas", "err");
      } }, "✅ Tekshirish"),
    );
  }

  // ------------------------------------------------------------------ 🏠 asosiy
  function renderHome() {
    const u = me.user;
    const initial = (u.first_name || u.username || "K").trim().charAt(0).toUpperCase();
    const vip = me.vip;
    const pending = me.pending.map((d) =>
      h("button", { class: "item", onclick: () => go(renderPayment, d) },
        h("div", { class: "ic" }, "⏳"),
        h("div", { class: "main" }, h("div", { class: "title" }, `To‘lov #${d.id} kutilmoqda`),
          h("div", { class: "sub" }, d.target === "wallet" ? "Hamyonni to‘ldirish" : `${d.bookmaker || "Mob-Cash"} • ID ${d.payer_id}`)),
        h("div", { class: "right" }, d.amount_text)));

    screen(
      h("div", { class: "header" },
        h("div", { class: "avatar" }, initial),
        h("div", {}, h("div", { class: "hello" }, "Xush kelibsiz 👋"), h("div", { class: "name" }, u.first_name || u.username || "Mehmon")),
        me.test_mode ? h("span", { class: "badge" }, "🧪 Test") : null),
      h("div", { class: "balance" },
        h("div", { class: "label" }, "Hamyon balansi"),
        h("div", { class: "amount" }, me.wallet.available_text),
        h("div", { class: "row" }, h("span", {}, "🎁 Bonus: " + me.wallet.bonus_text), h("span", {}, "📥 Jami: " + me.wallet.total_deposit_text)),
        vip ? h("div", { class: "vip-chip" }, "🏆 ", vip.level || "VIP yo‘q", vip.level ? ` • +${pct(vip.percent)}%` : "") : null),
      pending.length ? h("h2", {}, "Kutilayotgan to‘lovlar") : null,
      pending.length ? h("div", { class: "list" }, pending) : null,
      me.mobcash_enabled ? h("div", { class: "grid" },
        action("➕", "Hisob to‘ldirish", "O‘yin hisobiga", () => { setTab("deposit"); startDeposit(); }),
        action("➖", "Pul chiqarish", "Kartaga", () => { setTab("withdraw"); startWithdraw(); }),
        action("🏠", "Hamyonni to‘ldirish", "Bot hamyoniga", () => go(renderTopupAmount)),
        action("📋", "Tarix", "Oxirgi amallar", () => root("history")),
      ) : h("div", { class: "note" }, "Hisob to‘ldirish va pul chiqarish hozircha bot chatida ishlaydi."),
      me.support_url ? h("button", { class: "btn ghost", onclick: () => openLink(me.support_url) }, "👨‍💻 Qo‘llab-quvvatlash") : null,
    );
  }

  function action(icon, title, sub, onclick) {
    return h("button", { class: "action", onclick: () => { haptic("tap"); onclick(); } },
      h("div", { class: "ic" }, icon), h("div", { class: "t" }, title), h("div", { class: "s" }, sub));
  }

  function openLink(url) {
    let u = String(url).trim();
    if (u.startsWith("@")) u = "https://t.me/" + u.slice(1);
    if (tg && /^https:\/\/t\.me\//.test(u)) tg.openTelegramLink(u);
    else if (tg) tg.openLink(u); else window.open(u, "_blank");
  }

  function steps(n, total) {
    return h("div", { class: "steps" }, Array.from({ length: total }, (_, i) => h("i", { class: i < n ? "on" : "" })));
  }

  // ------------------------------------------------------------------ kantora tanlash
  function chooseBookmaker(title, next) {
    const list = me.bookmakers;
    if (!list.length) {
      screen(h("div", { class: "empty" }, h("div", { class: "e" }, "🏢"), h("p", {}, "Hozircha faol kantora yo‘q. Tez orada ishga tushadi.")));
      return;
    }
    if (list.length === 1) { next(list[0]); return; }
    screen(
      h("h1", {}, title), h("p", { class: "muted" }, "Kantorani tanlang 👇"),
      h("div", { class: "list" }, list.map((bm) =>
        h("button", { class: "item", onclick: () => { haptic("tap"); go(next, bm); } },
          h("div", { class: "ic" }, "🏢"),
          h("div", { class: "main" }, h("div", { class: "title" }, bm.name),
            bm.payer_id ? h("div", { class: "sub" }, "ID: " + bm.payer_id) : null),
          h("span", { class: "chev" }, "›")))),
    );
  }

  // ------------------------------------------------------------------ ➕ hisob to‘ldirish
  function startDeposit() {
    if (!me.mobcash_enabled) { renderDisabled(); return; }
    const game = me.pending.find((d) => d.target === "game");
    if (game) { renderPayment(game); return; }
    chooseBookmaker("➕ Hisob to‘ldirish", (bm) => renderPayerStep(bm, "dep"));
  }

  function renderPayerStep(bm, flow) {
    const input = h("input", { class: "input", inputmode: "numeric", placeholder: "Masalan: 123456789", value: bm.payer_id || "" });
    const btn = h("button", { class: "btn", onclick: async () => {
      const payer = digits(input.value);
      if (payer.length < 5) { toast("ID kamida 5 ta raqamdan iborat bo‘lsin", "err"); return; }
      if (flow === "dep") {
        const r = await withBusy(btn, () => api("POST", "/payer", { bookmaker_id: bm.id, payer_id: payer }));
        if (r) { bm.payer_id = payer; go(renderAmountStep, bm, payer, r.nickname); }
      } else {
        bm.payer_id = payer; go(renderCodeStep, bm, payer);
      }
    } }, "Davom etish");
    screen(
      steps(1, flow === "dep" ? 3 : 4),
      h("h1", {}, flow === "dep" ? "O‘yin ID raqami" : "Pul chiqarish"),
      h("p", { class: "muted" }, `🏢 ${bm.name}`),
      h("div", { class: "field" }, h("label", {}, "O‘yin hisobingiz ID raqami"), input),
      h("div", { class: "note small" }, "ID raqamni o‘yin ilovasidagi profil bo‘limidan topasiz."),
      btn,
    );
    setTimeout(() => input.focus(), 150);
  }

  function amountField(min, max, onSubmit, label) {
    const input = h("input", { class: "input", inputmode: "numeric", placeholder: "Summani kiriting" });
    input.addEventListener("input", () => {
      const d = digits(input.value);
      input.value = d ? d.replace(/\B(?=(\d{3})+(?!\d))/g, " ") : "";
    });
    const chips = h("div", { class: "chips" }, QUICK.filter((v) => v >= Number(min) && v <= Number(max)).map((v) =>
      h("button", { class: "chip", onclick: () => { input.value = String(v).replace(/\B(?=(\d{3})+(?!\d))/g, " "); haptic("tap"); } }, fmt(v))));
    const btn = h("button", { class: "btn", onclick: () => {
      const val = Number(digits(input.value));
      if (!val) { toast("Summani kiriting", "err"); return; }
      if (val < Number(min) || val > Number(max)) { toast(`Summa ${fmt(min)} — ${fmt(max)} oralig‘ida bo‘lsin`, "err"); return; }
      onSubmit(val, btn);
    } }, label || "To‘lovga o‘tish");
    return [h("div", { class: "field" }, h("label", {}, `Summa (${fmt(min)} — ${fmt(max)})`), input, chips), btn];
  }

  function renderAmountStep(bm, payer, nickname) {
    const L = me.limits;
    screen(
      steps(2, 3),
      h("h1", {}, "Summani tanlang"),
      h("p", { class: "muted" }, `🏢 ${bm.name} • ID ${payer}`),
      h("div", { class: "nick" }, "✅ ", nickname),
      ...amountField(L.deposit_min, L.deposit_max, async (val, btn) => {
        const d = await withBusy(btn, () => api("POST", "/deposits", { bookmaker_id: bm.id, payer_id: payer, amount: val }));
        if (d) { await refresh(); backStack.length = 0; go(renderPayment, d); }
      }),
      Number(L.deposit_fee) > 0 ? h("div", { class: "note small" }, `Komissiya: ${pct(L.deposit_fee)}%`) : null,
    );
  }

  // ------------------------------------------------------------------ 🏠 hamyonni to‘ldirish
  function renderTopupAmount() {
    const wallet = me.pending.find((d) => d.target === "wallet");
    if (wallet) { renderPayment(wallet); return; }
    const L = me.limits;
    screen(
      h("h1", {}, "🏠 Hamyonni to‘ldirish"),
      h("p", { class: "muted" }, "Pul to‘g‘ridan-to‘g‘ri bot hamyoningizga tushadi."),
      ...amountField(L.deposit_min, L.deposit_max, async (val, btn) => {
        const d = await withBusy(btn, () => api("POST", "/topups", { amount: val }));
        if (d) { await refresh(); backStack.length = 0; go(renderPayment, d); }
      }),
    );
  }

  // ------------------------------------------------------------------ 💳 to‘lov sahifasi
  function statusPill(status, text) {
    const cls = { credited: "ok", paid: "warn", pending: "warn", review: "warn", awaiting_payout: "warn",
      expired: "bad", cancelled: "bad", rejected: "bad", failed: "bad", refunded: "bad" }[status] || "";
    return h("span", { class: "pill " + cls }, text);
  }

  function renderPayment(d) {
    if (d.status === "credited") { renderSuccess(d); return; }
    const timer = h("span", { class: "timer" }, "--:--");
    const pill = statusPill(d.status, d.status_text);
    const card = d.card;
    const isPending = d.status === "pending";
    screen(
      h("div", { class: "card pay-amount" },
        h("div", { class: "muted small" }, "Aynan shu summani o‘tkazing"),
        h("div", { class: "big" }, d.amount_text),
        h("button", { class: "copy", onclick: () => copy(digits(d.amount.split(".")[0]), "Summa") }, "📋 Summani nusxalash"),
        h("div", { style: "margin-top:10px" }, pill)),
      h("div", { class: "note warn small" },
        "⚠️ Summani bir so‘m ham o‘zgartirmang — to‘lov aynan shu summa bo‘yicha avtomatik tasdiqlanadi."),
      card ? h("div", { class: "card" },
        h("div", { class: "kv" }, h("span", { class: "k" }, "Karta raqami"),
          h("button", { class: "copy", onclick: () => copy(card.raw, "Karta raqami") }, "📋")),
        h("div", { class: "card-num" }, card.number),
        h("div", { class: "kv" }, h("span", { class: "k" }, "Karta egasi"), h("span", { class: "v" }, card.holder || "—")),
        card.bank ? h("div", { class: "kv" }, h("span", { class: "k" }, "Bank"), h("span", { class: "v" }, card.bank)) : null,
      ) : null,
      h("div", { class: "card" },
        h("div", { class: "kv" }, h("span", { class: "k" }, "To‘lov"), h("span", { class: "v" }, "#" + d.id)),
        d.target === "game" ? h("div", { class: "kv" }, h("span", { class: "k" }, "Kantora"), h("span", { class: "v" }, d.bookmaker || "Mob-Cash")) : null,
        d.target === "game" ? h("div", { class: "kv" }, h("span", { class: "k" }, "O‘yin ID"), h("span", { class: "v" }, d.payer_id)) : null,
        h("div", { class: "kv" }, h("span", { class: "k" }, "Hisobga tushadi"), h("span", { class: "v" }, d.credit_text)),
        isPending ? h("div", { class: "kv" }, h("span", { class: "k" }, "Qolgan vaqt"), timer) : null,
      ),
      isPending ? h("p", { class: "muted small center" }, "To‘lov tushishi bilan avtomatik tasdiqlanadi — sahifani yopsangiz ham bot xabar beradi.") : null,
      isPending ? h("button", { class: "btn danger", onclick: async (e) => {
        if (!(await confirmDialog("To‘lovni bekor qilasizmi?"))) return;
        const r = await withBusy(e.currentTarget, () => api("POST", `/deposits/${d.id}/cancel`));
        if (r) { toast("To‘lov bekor qilindi", "ok"); await refresh(); root("home"); }
      } }, "Bekor qilish") : h("button", { class: "btn ghost", onclick: () => root("home") }, "🏠 Bosh sahifa"),
    );
    if (isPending) {
      const end = new Date(d.expires_at).getTime();
      const tick = () => {
        const left = Math.max(0, Math.floor((end - Date.now()) / 1000));
        timer.textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
      };
      tick();
      tickTimer = setInterval(tick, 1000);
    }
    if (["pending", "paid"].includes(d.status)) {
      pollTimer = setInterval(async () => {
        try {
          const fresh = await api("GET", `/deposits/${d.id}`);
          if (fresh.status !== d.status) {
            if (fresh.status === "credited") { haptic("ok"); await refresh(); }
            renderPayment(fresh);
          }
        } catch (_) { /* tarmoq uzilishi — keyingi urinish */ }
      }, 5000);
    }
  }

  function renderSuccess(d) {
    screen(
      h("div", { class: "success" },
        h("div", { class: "ring" }, "✓"),
        h("h1", {}, "To‘lov tasdiqlandi!"),
        h("p", { class: "muted" }, d.target === "wallet"
          ? `${d.credit_text} hamyoningizga tushdi.`
          : `${d.credit_text} — ${d.bookmaker || "o‘yin"} hisobingizga (ID ${d.payer_id}) tushirildi.`)),
      h("button", { class: "btn", onclick: () => root("home") }, "🏠 Bosh sahifa"),
    );
  }

  function confirmDialog(text) {
    return new Promise((resolve) => {
      if (tg && tg.showConfirm) tg.showConfirm(text, (ok) => resolve(Boolean(ok)));
      else resolve(window.confirm(text));
    });
  }

  // ------------------------------------------------------------------ ➖ pul chiqarish
  function startWithdraw() {
    if (!me.mobcash_enabled) { renderDisabled(); return; }
    chooseBookmaker("➖ Pul chiqarish", (bm) => renderPayerStep(bm, "wd"));
  }

  function renderCodeStep(bm, payer) {
    const input = h("input", { class: "input", placeholder: "Yechish kodi", autocomplete: "off", autocapitalize: "off", spellcheck: "false" });
    const btn = h("button", { class: "btn", onclick: async () => {
      const code = input.value.trim();
      if (code.length < 4) { toast("Yechish kodini kiriting", "err"); return; }
      const q = await withBusy(btn, () => api("POST", "/withdrawals/quote", { bookmaker_id: bm.id, payer_id: payer, code }));
      if (q) go(renderCardStep, bm, payer, code, q);
    } }, "Summani tekshirish");
    screen(
      steps(2, 4),
      h("h1", {}, "Yechish kodi"),
      h("p", { class: "muted" }, `🏢 ${bm.name} • ID ${payer}`),
      h("div", { class: "note small" },
        "1️⃣ O‘yin ilovasida «Pul chiqarish» → kassa orqali naqd pul usulini tanlang.\n",
        h("br"), "2️⃣ Summani kiriting va ilova bergan ", h("b", {}, "yechish kodini"), " shu yerga yozing."),
      h("div", { class: "field" }, h("label", {}, `Limit: ${me.limits.withdraw_min_text} — ${me.limits.withdraw_max_text}`), input),
      btn,
    );
    setTimeout(() => input.focus(), 150);
  }

  function renderCardStep(bm, payer, code, q) {
    const input = h("input", { class: "input card-num", inputmode: "numeric", placeholder: "8600 0000 0000 0000", maxlength: "19" });
    input.addEventListener("input", () => { input.value = digits(input.value).slice(0, 16).replace(/(\d{4})(?=\d)/g, "$1 "); });
    const proceed = (card, label) => go(renderWithdrawConfirm, bm, payer, code, q, card, label);
    screen(
      steps(3, 4),
      h("h1", {}, "Qaysi kartaga?"),
      h("div", { class: "card" },
        h("div", { class: "kv" }, h("span", { class: "k" }, "Yechiladi"), h("span", { class: "v" }, q.amount_text)),
        h("div", { class: "kv" }, h("span", { class: "k" }, "Komissiya"), h("span", { class: "v" }, q.fee_text)),
        h("div", { class: "kv" }, h("span", { class: "k" }, "Kartaga tushadi"), h("span", { class: "v" }, q.payout_text))),
      me.saved_card ? h("button", { class: "btn ghost", onclick: () => proceed("saved", me.saved_card) }, "💳 " + me.saved_card) : null,
      h("div", { class: "field" }, h("label", {}, "Yangi karta raqami (16 raqam)"), input),
      h("button", { class: "btn", onclick: () => {
        const card = digits(input.value);
        if (card.length !== 16) { toast("Karta raqami 16 ta raqamdan iborat bo‘lsin", "err"); return; }
        proceed(card, card.slice(0, 4) + " **** **** " + card.slice(-4));
      } }, "Davom etish"),
    );
  }

  function renderWithdrawConfirm(bm, payer, code, q, card, cardLabel) {
    const btn = h("button", { class: "btn", onclick: async () => {
      if (!(await confirmDialog(`${q.payout_text} kartaga o‘tkazilsinmi?`))) return;
      const wd = await withBusy(btn, () => api("POST", "/withdrawals", { bookmaker_id: bm.id, payer_id: payer, code, card }));
      if (wd) { await refresh(); backStack.length = 0; updateBack(); renderWithdrawDone(wd); }
    } }, "✅ Tasdiqlash");
    screen(
      steps(4, 4),
      h("h1", {}, "Tasdiqlang"),
      h("div", { class: "card" },
        h("div", { class: "kv" }, h("span", { class: "k" }, "Kantora"), h("span", { class: "v" }, bm.name)),
        h("div", { class: "kv" }, h("span", { class: "k" }, "O‘yin ID"), h("span", { class: "v" }, payer)),
        h("div", { class: "kv" }, h("span", { class: "k" }, "Yechiladi"), h("span", { class: "v" }, q.amount_text)),
        h("div", { class: "kv" }, h("span", { class: "k" }, "Komissiya"), h("span", { class: "v" }, q.fee_text)),
        h("div", { class: "kv" }, h("span", { class: "k" }, "Kartaga"), h("span", { class: "v" }, q.payout_text)),
        h("div", { class: "kv" }, h("span", { class: "k" }, "Karta"), h("span", { class: "v" }, cardLabel))),
      btn,
    );
  }

  function renderWithdrawDone(wd) {
    const review = wd.status === "review";
    screen(
      h("div", { class: "success" },
        h("div", { class: "ring", style: review ? "background:var(--warn)" : "" }, review ? "⏳" : "✓"),
        h("h1", {}, review ? "Ariza tekshiruvda" : "Ariza qabul qilindi!"),
        h("p", { class: "muted" }, review
          ? "Kassa javobi kechikdi. Administrator tekshirib, natijasini botda xabar qiladi."
          : `${wd.payout_text} tez orada ${wd.card} kartangizga o‘tkaziladi. Bot xabar beradi.`)),
      h("button", { class: "btn", onclick: () => root("home") }, "🏠 Bosh sahifa"),
    );
  }

  function renderDisabled() {
    screen(h("div", { class: "empty" }, h("div", { class: "e" }, "💬"), h("p", {}, "Bu bo‘lim hozir bot chatida ishlaydi.")));
  }

  // ------------------------------------------------------------------ 📋 tarix
  async function renderHistory(which) {
    which = which || "in";
    screen(h("div", { class: "splash" }, h("div", { class: "spinner" })));
    let data;
    try { data = await api("GET", "/history"); } catch (e) { toast(e.message, "err"); return; }
    const seg = h("div", { class: "seg" },
      h("button", { class: which === "in" ? "on" : "", onclick: () => renderHistory("in") }, "📥 Kirim"),
      h("button", { class: which === "out" ? "on" : "", onclick: () => renderHistory("out") }, "📤 Chiqim"));
    const date = (s) => (s ? new Date(s).toLocaleString("uz-UZ", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "");
    const rows = which === "in"
      ? data.deposits.map((d) => h("button", { class: "item", onclick: () => (d.status === "pending" ? go(renderPayment, d) : null) },
          h("div", { class: "ic" }, d.target === "wallet" ? "🏠" : "📥"),
          h("div", { class: "main" }, h("div", { class: "title" }, d.target === "wallet" ? "Hamyonni to‘ldirish" : `${d.bookmaker || "Mob-Cash"} • ${d.payer_id}`),
            h("div", { class: "sub" }, `#${d.id} • ${date(d.created_at)}`), statusPill(d.status, d.status_text)),
          h("div", { class: "right" }, d.amount_text)))
      : data.withdrawals.map((w) => h("div", { class: "item" },
          h("div", { class: "ic" }, "📤"),
          h("div", { class: "main" }, h("div", { class: "title" }, `${w.bookmaker || "Mob-Cash"} → ${w.card}`),
            h("div", { class: "sub" }, `#${w.id} • ${date(w.created_at)}`), statusPill(w.status, w.status_text)),
          h("div", { class: "right" }, w.payout_text)));
    screen(
      h("h1", {}, "📋 Tarix"), seg,
      rows.length ? h("div", { class: "list" }, rows) : h("div", { class: "empty" }, h("div", { class: "e" }, "🗂"), "Hali amallar yo‘q"),
    );
  }

  // ------------------------------------------------------------------ 🎁 bonus
  function renderBonus() {
    const vip = me.vip;
    const ref = me.referral;
    const promo = h("input", { class: "input", placeholder: "PROMOKOD", autocapitalize: "characters", maxlength: "32" });
    screen(
      h("h1", {}, "🎁 Bonuslar"),
      vip ? h("div", { class: "card" },
        h("div", { class: "kv" }, h("span", { class: "k" }, "🏆 VIP daraja"), h("span", { class: "v" }, vip.level ? `${vip.level} (+${pct(vip.percent)}%)` : "Hali yo‘q")),
        vip.next ? h("div", {},
          h("div", { class: "bar" }, h("i", { style: `width:${Math.max(3, vip.progress)}%` })),
          h("div", { class: "small muted" }, `${vip.next} darajasigacha ${vip.left_text} qoldi (${vip.progress}%)`))
          : h("div", { class: "small muted" }, vip.levels.length ? "Siz eng yuqori darajadasiz 🎉" : ""),
        vip.levels.length ? h("div", { style: "margin-top:10px" }, vip.levels.map((lv) =>
          h("div", { class: "kv" }, h("span", { class: "k" }, (lv.current ? "✅ " : "▫️ ") + lv.name),
            h("span", { class: "v small" }, `${lv.from_text} dan • +${pct(lv.percent)}%`)))) : null,
      ) : null,
      ref ? h("div", { class: "card" },
        h("div", { class: "kv" }, h("span", { class: "k" }, "🤝 Referal"), h("span", { class: "v" }, `${pct(ref.percent)}% har depozitdan`)),
        h("div", { class: "kv" }, h("span", { class: "k" }, "Taklif qilinganlar"), h("span", { class: "v" }, ref.count)),
        h("div", { class: "kv" }, h("span", { class: "k" }, "Ishlangan"), h("span", { class: "v" }, ref.earned_text)),
        h("button", { class: "btn ghost", onclick: () => copy(ref.link, "Havola") }, "📋 Havolani nusxalash"),
        h("button", { class: "btn", onclick: () => {
          const url = "https://t.me/share/url?url=" + encodeURIComponent(ref.link) + "&text=" + encodeURIComponent("Qulay kassa bot — qo‘shiling!");
          tg ? tg.openTelegramLink(url) : window.open(url);
        } }, "📤 Do‘stlarga yuborish"),
      ) : null,
      h("div", { class: "card" },
        h("div", { class: "field", style: "margin-top:0" }, h("label", {}, "🎟 Promokod"), promo),
        h("button", { class: "btn", onclick: async (e) => {
          const code = promo.value.trim();
          if (!code) { toast("Promokodni kiriting", "err"); return; }
          const r = await withBusy(e.currentTarget, () => api("POST", "/promo", { code }));
          if (r) { toast(r.message, "ok"); promo.value = ""; await refresh(); }
        } }, "Faollashtirish")),
    );
  }

  async function refresh() { try { await load(); } catch (_) { /* keyingi safar */ } }

  boot();
})();
