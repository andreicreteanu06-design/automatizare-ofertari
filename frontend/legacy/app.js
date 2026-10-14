/* Ofertare UI — JS simplu, fără dependențe, fără CDN.
 * REGULĂ: datele de la server (inclusiv text din PDF-uri de la furnizori) intră în pagină
 * DOAR prin textContent / el(). Niciodată innerHTML. */
"use strict";

// ---------- utilitare ----------------------------------------------------------------

function el(tag, attrs, children) {
  var node = document.createElement(tag);
  Object.keys(attrs || {}).forEach(function (k) {
    if (k === "text") node.textContent = attrs[k];
    else if (k === "class") node.className = attrs[k];
    else if (k.indexOf("on") === 0) node.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] === true) node.setAttribute(k, "");
    else if (attrs[k] !== false && attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
  });
  (children || []).forEach(function (c) { node.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
  return node;
}

function $(sel, root) { return (root || document).querySelector(sel); }
function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

function detailText(detail) {
  if (!detail) return "eroare necunoscută";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(function (d) { return (d.loc || []).slice(1).join(".") + ": " + d.msg; }).join("; ");
  var parts = [detail.error || ""];
  if (detail.rules) parts.push("reguli: " + detail.rules.join(", "));
  if (detail.missing_codes && detail.missing_codes.length) parts.push("coduri lipsă: " + detail.missing_codes.join(", "));
  if (detail.invented_codes && detail.invented_codes.length) parts.push("coduri inventate: " + detail.invented_codes.join(", "));
  return parts.filter(Boolean).join(" — ");
}

async function api(path, body, expectBlob) {
  var opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  var res = await fetch("/api" + path, opts);
  if (!res.ok) {
    var detail = null;
    try { detail = (await res.json()).detail; } catch (e) { detail = res.statusText; }
    var err = new Error(detailText(detail));
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return expectBlob ? res : res.json();
}

function busy(statusEl, label) {
  var start = Date.now();
  statusEl.classList.remove("error");
  var tick = function () {
    var s = Math.round((Date.now() - start) / 1000);
    statusEl.textContent = label + " " + Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  };
  tick();
  var id = setInterval(tick, 1000);
  return function (message, isError) {
    clearInterval(id);
    statusEl.textContent = message || "";
    statusEl.classList.toggle("error", !!isError);
  };
}

function fmtEur(s) {
  var n = Number(s);
  return isNaN(n) ? s : n.toLocaleString("ro-RO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ---------- tab-uri -----------------------------------------------------------------

$all(".tab").forEach(function (btn) {
  btn.addEventListener("click", function () {
    $all(".tab").forEach(function (b) { b.classList.toggle("active", b === btn); });
    $all(".panel").forEach(function (p) { p.hidden = p.id !== "tab-" + btn.dataset.tab; });
  });
});

// ---------- CHAT --------------------------------------------------------------------

var CITE_OR_REMOVED = /(\[[A-Za-z0-9_.-]+:\d+(?:-\d+)?\]|\[cod neverificat\])/g;

function renderAnswer(text) {
  var p = el("div", { class: "a" });
  text.split(CITE_OR_REMOVED).forEach(function (part) {
    if (!part) return;
    if (part === "[cod neverificat]") p.appendChild(el("span", { class: "removed", text: "cod neverificat", title: "Cod eliminat: nu apare în sursa citată" }));
    else if (/^\[[A-Za-z0-9_.-]+:\d+(?:-\d+)?\]$/.test(part)) p.appendChild(el("span", { class: "cite", text: part }));
    else p.appendChild(document.createTextNode(part));
  });
  return p;
}

function renderChat(question, res) {
  var card = el("div", { class: "qa" }, [el("div", { class: "q", text: question }), renderAnswer(res.answer)]);
  if (!res.grounded) card.appendChild(el("div", { class: "warn", text: "⚠ Răspuns fără citări valide — nu te baza pe el." }));
  if (res.removed_codes.length) card.appendChild(el("div", { class: "warn", text: "Coduri eliminate (nu apar în sursele citate): " + res.removed_codes.join(", ") }));
  if (res.citations.length) {
    card.appendChild(el("div", { class: "meta" }, ["Surse: "].concat(res.citations.map(function (c) {
      return el("span", { class: "cite", text: c.cite + " " + [c.doc_type, c.supplier].filter(Boolean).join(" · ") });
    }).reduce(function (acc, x) { return acc.concat([x, " "]); }, []))));
  }
  if (res.exact.length) {
    var rows = res.exact.map(function (r) {
      return el("tr", {}, [el("td", { text: r.supplier }), el("td", { text: r.seller_code || "" }), el("td", { text: r.name }),
        el("td", { text: r.issue_date }), el("td", { class: "num", text: fmtEur(r.net_unit_price) }), el("td", { text: r.currency })]);
    });
    card.appendChild(el("div", { class: "meta", text: "Istoric achiziții (intern, din e-Factura):" }));
    card.appendChild(el("table", {}, [el("thead", {}, [el("tr", {}, ["Furnizor", "Cod", "Articol", "Data", "Preț net/buc", "Monedă"].map(function (h) {
      return el("th", { text: h, class: h.indexOf("Preț") === 0 ? "num" : "" });
    }))]), el("tbody", {}, rows)]));
  }
  $("#chat-log").prepend(card);
}

$("#chat-form").addEventListener("submit", async function (e) {
  e.preventDefault();
  var q = $("#chat-q").value.trim();
  if (!q) return;
  var btn = $("#chat-form button[type=submit]");
  btn.disabled = true;
  var done = busy($("#chat-status"), "Colibri lucrează (pe CPU poate dura câteva minute)…");
  try {
    renderChat(q, await api("/chat", { query: q }));
    done("");
    $("#chat-q").value = "";
  } catch (err) {
    done("Eroare: " + err.message, true);
  } finally {
    btn.disabled = false;
  }
});

// ---------- OFERTĂ ------------------------------------------------------------------

var CURRENCIES = ["EUR", "RON", "USD", "GBP", "CHF", "PLN", "CZK", "HUF", "SEK", "JPY", "CNY"];

function currencySelect(name, value) {
  return el("select", { name: name }, CURRENCIES.map(function (c) { return el("option", { value: c, selected: c === value, text: c }); }));
}

function removeBtn() {
  return el("button", { type: "button", class: "icon", title: "Șterge", text: "✕", onclick: function (e) {
    e.target.closest("tr").remove();
    markStale();
  } });
}

async function fillFromInvoices(tr) {
  var code = $("[name=code]", tr).value.trim();
  var hint = $(".price-hint", tr);
  if (code.length < 2) return;
  hint.textContent = "caut…";
  try {
    var res = await api("/prices?code=" + encodeURIComponent(code));
    var last = res.history[0];
    if (!last) { hint.textContent = "fără istoric"; return; }
    $("[name=unit_price]", tr).value = last.net_unit_price;
    $("[name=price_currency]", tr).value = CURRENCIES.indexOf(last.currency) >= 0 ? last.currency : "EUR";
    if (!$("[name=supplier]", tr).value) $("[name=supplier]", tr).value = last.supplier;
    if (!$("[name=description]", tr).value) $("[name=description]", tr).value = last.name;
    hint.textContent = "ultima factură: " + last.issue_date + " · " + last.supplier;
    markStale();
  } catch (err) {
    hint.textContent = "eroare: " + err.message;
  }
}

function addLine(data) {
  data = data || {};
  var tr = el("tr", {}, [
    el("td", {}, [el("input", { name: "code", required: true, maxlength: 64, value: data.code || "" }), el("span", { class: "price-hint" })]),
    el("td", {}, [el("button", { type: "button", class: "icon", title: "Preț din ultima factură", text: "↺", onclick: function () { fillFromInvoices(tr); } })]),
    el("td", {}, [el("input", { name: "description", required: true, maxlength: 500, value: data.description || "" })]),
    el("td", {}, [el("input", { name: "supplier", required: true, maxlength: 200, value: data.supplier || "" })]),
    el("td", {}, [el("input", { name: "manufacturer", maxlength: 200 })]),
    el("td", {}, [el("input", { name: "quantity", type: "number", min: "0", step: "any", required: true, value: data.quantity || "1" })]),
    el("td", {}, [el("input", { name: "unit_price", type: "number", min: "0", step: "any", required: true })]),
    el("td", {}, [currencySelect("price_currency", "EUR")]),
    el("td", {}, [el("input", { name: "transport_cost", type: "number", min: "0", step: "any", value: "0" })]),
    el("td", {}, [currencySelect("transport_currency", "EUR")]),
    el("td", {}, [el("input", { name: "duty_rate_percent", type: "number", min: "0", max: "100", step: "any", value: "0" })]),
    el("td", {}, [el("input", { name: "imported", type: "checkbox" })]),
    el("td", {}, [el("input", { name: "afer_agreement", maxlength: 100, placeholder: "doar pt. import" })]),
    el("td", {}, [removeBtn()])
  ]);
  $("[name=code]", tr).addEventListener("change", function () { fillFromInvoices(tr); });
  $("#lines").appendChild(tr);
}

function addCert() {
  $("#certs").appendChild(el("tr", {}, [
    el("td", {}, [el("input", { name: "supplier", required: true, maxlength: 200 })]),
    el("td", {}, [el("select", { name: "standard" }, [el("option", { text: "ISO/TS 22163" }), el("option", { text: "ISO 9001" })])]),
    el("td", {}, [el("input", { name: "number", required: true, maxlength: 100 })]),
    el("td", {}, [el("input", { name: "valid_until", type: "date", required: true })]),
    el("td", {}, [removeBtn()])
  ]));
}

function rowValues(tr) {
  var v = {};
  $all("input, select", tr).forEach(function (i) { v[i.name] = i.type === "checkbox" ? i.checked : i.value.trim(); });
  return v;
}

function offerPayload() {
  var f = $("#offer-form");
  var val = function (n) { return f.elements[n].value.trim(); };
  return {
    offer_number: val("offer_number"), client_name: val("client_name"), offer_date: val("offer_date"),
    validity_days: Number(val("validity_days")), markup_percent: val("markup_percent"), delivery_terms: val("delivery_terms") || "DAP",
    currency: "EUR",
    firm_prices: f.elements.firm_prices.checked,
    spare_parts_years: f.elements.spare_parts_ok.checked ? 30 : 0,
    spare_parts_reference: val("spare_parts_reference"),
    include_penalty_clause: f.elements.include_penalty_clause.checked,
    penalty_percent_per_week: "5", penalty_cap_percent: "30",
    // câmpurile Saga: ignorate de /offers/calculate, folosite de /offers/export/saga
    client_cif: val("client_cif"), document_number: val("document_number"), vat_percent: val("vat_percent") || "21",
    certificates: $all("#certs tr").map(rowValues),
    lines: $all("#lines tr").map(function (tr) {
      var v = rowValues(tr);
      return { code: v.code, description: v.description, supplier: v.supplier, manufacturer: v.manufacturer,
        quantity: v.quantity, unit: "BUC", unit_price: v.unit_price, price_currency: v.price_currency,
        transport_cost: v.transport_cost || "0", transport_currency: v.transport_currency,
        duty_rate_percent: v.duty_rate_percent || "0", imported: v.imported, afer_agreement: v.afer_agreement || null };
    })
  };
}

var REQ_CODES = { afer: ["AFER_MISSING"], iso: ["CERT_MISSING", "CERT_EXPIRED"], spare: ["SPARE_PARTS_30Y"],
  penalty: ["PENALTY_CLAUSE"], eur: ["CURRENCY_NOT_EUR", "PRICES_NOT_FIRM"] };

function showChecklist(compliance) {
  var codes = compliance ? compliance.failures.map(function (f) { return f.code; }) : null;
  $all("#chk-list li").forEach(function (li) {
    var bad = codes && REQ_CODES[li.dataset.req].some(function (c) { return codes.indexOf(c) >= 0; });
    li.classList.toggle("ok", !!codes && !bad);
    li.classList.toggle("bad", !!bad);
  });
  var badge = $("#chk-badge");
  badge.className = "badge" + (codes ? (compliance.ok ? " ok" : " bad") : "");
  badge.textContent = codes ? (compliance.ok ? "validat" : "blocat") : "necalculat";
  var list = $("#chk-failures");
  list.textContent = "";
  (compliance ? compliance.failures : []).forEach(function (f) { list.appendChild(el("li", { text: f.message })); });
}

var lastCalc = null;

function markStale() {
  // Orice modificare după calcul invalidează rezultatul: descărcarea cere un calcul nou.
  if (!lastCalc) return;
  lastCalc = null;
  $("#dl-docx").disabled = $("#dl-xlsx").disabled = $("#dl-saga").disabled = true;
  $("#offer-result").classList.add("stale");
  showChecklist(null);
  $("#offer-status").textContent = "Datele s-au schimbat — recalculează.";
}

function renderOffer(res) {
  var out = $("#offer-result");
  out.textContent = "";
  out.classList.remove("stale");
  out.appendChild(el("div", { class: "totals" }, [
    el("div", {}, ["Total vânzare (EUR)", el("strong", { text: fmtEur(res.total_sale_eur) })]),
    el("div", {}, ["Cost total livrat (EUR)", el("strong", { text: fmtEur(res.total_landed_eur) })]),
    el("div", {}, ["Marjă (EUR)", el("strong", { text: fmtEur(res.total_margin_eur) })]),
    el("div", {}, ["Marjă din vânzare", el("strong", { text: res.margin_on_sale_percent + "%" })]),
    el("div", {}, ["Curs BNR " + res.fx.date, el("strong", { text: "1 EUR = " + res.fx.eur_ron + " RON" })])
  ]));
  var heads = ["Cod", "Preț EUR/buc", "Transport/buc", "Taxă vamală/buc", "Cost livrat/buc", "Preț vânzare/buc", "Total linie", "Marjă"];
  var keys = ["price_eur", "transport_eur", "duty_eur", "landed_eur", "sale_unit_eur", "sale_total_eur", "margin_eur"];
  out.appendChild(el("div", { class: "table-wrap" }, [el("table", {}, [
    el("thead", {}, [el("tr", {}, heads.map(function (h, i) { return el("th", { text: h, class: i ? "num" : "" }); }))]),
    el("tbody", {}, res.lines.map(function (l) {
      return el("tr", {}, [el("td", { text: l.code })].concat(keys.map(function (k) { return el("td", { class: "num", text: fmtEur(l[k]) }); })));
    }))
  ])]));
}

$("#offer-form").addEventListener("input", markStale);
$("#add-line").addEventListener("click", function () { addLine(); markStale(); });
$("#add-cert").addEventListener("click", function () { addCert(); markStale(); });

$("#offer-form").addEventListener("submit", async function (e) {
  e.preventDefault();
  var done = busy($("#offer-status"), "Calculez (curs BNR prin research-gateway)…");
  try {
    var payload = offerPayload();
    var res = await api("/offers/calculate", payload);
    renderOffer(res);
    showChecklist(res.compliance);
    lastCalc = payload;
    $("#dl-docx").disabled = $("#dl-xlsx").disabled = $("#dl-saga").disabled = !res.compliance.ok;
    done(res.compliance.ok ? "Gata. Checklist validat — poți descărca." : "Calculat. Checklist incomplet — descărcarea e blocată.", !res.compliance.ok);
  } catch (err) {
    done("Eroare: " + err.message, true);
  }
});

async function download(kind) {
  if (!lastCalc) return;
  var done = busy($("#offer-status"), "Generez documentul…");
  try {
    var res = await api("/offers/export/" + kind, lastCalc, true);
    var name = (/filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "") || [])[1] || "oferta." + kind;
    var url = URL.createObjectURL(await res.blob());
    var a = el("a", { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    done("Descărcat: " + name);
  } catch (err) {
    if (err.status === 409 && err.detail && err.detail.failures) showChecklist({ ok: false, failures: err.detail.failures });
    done("Export refuzat: " + err.message, true);
  }
}
$("#dl-docx").addEventListener("click", function () { download("docx"); });
$("#dl-xlsx").addEventListener("click", function () { download("xlsx"); });
$("#dl-saga").addEventListener("click", function () {
  if (!lastCalc.client_cif || !lastCalc.document_number) {
    $("#offer-status").textContent = "Pentru Saga completează CUI client și Nr. document, apoi recalculează.";
    $("#offer-status").classList.add("error");
    return;
  }
  download("saga");
});

// ---------- E-MAIL ------------------------------------------------------------------

function addEmailItem(data) {
  data = data || {};
  $("#email-items").appendChild(el("tr", {}, [
    el("td", {}, [el("input", { name: "code", required: true, maxlength: 64, value: data.code || "" })]),
    el("td", {}, [el("input", { name: "description", maxlength: 300, value: data.description || "" })]),
    el("td", {}, [el("input", { name: "quantity", type: "number", min: "0", step: "any", value: data.quantity || "" })]),
    el("td", {}, [el("input", { name: "unit", maxlength: 20, value: data.unit || "pcs" })]),
    el("td", {}, [el("button", { type: "button", class: "icon", text: "✕", onclick: function (e) { e.target.closest("tr").remove(); } })])
  ]));
}

$("#add-email-item").addEventListener("click", function () { addEmailItem(); });
$("#copy-from-offer").addEventListener("click", function () {
  $("#email-items").textContent = "";
  $all("#lines tr").forEach(function (tr) {
    var v = rowValues(tr);
    if (v.code) addEmailItem({ code: v.code, description: v.description, quantity: v.quantity });
  });
  if (!$("#email-items tr")) addEmailItem();
});

$("#email-form").elements.kind.addEventListener("change", function (e) {
  $("#questions-wrap").hidden = e.target.value !== "clarification";
});

$("#email-form").addEventListener("submit", async function (e) {
  e.preventDefault();
  var f = e.target;
  var v = function (n) { return f.elements[n].value.trim(); };
  var payload = {
    kind: v("kind"), language: v("language"), contact_name: v("contact_name"), reply_by: v("reply_by") || null,
    sender_name: v("sender_name"), sender_company: v("sender_company"),
    questions: v("questions").split("\n").map(function (q) { return q.trim(); }).filter(Boolean),
    items: $all("#email-items tr").map(rowValues).filter(function (i) { return i.code; }).map(function (i) {
      return { code: i.code, description: i.description, quantity: i.quantity || null, unit: i.unit || "pcs" };
    })
  };
  $("#email-result").hidden = true;
  var needsLlm = ["ro", "en"].indexOf(payload.language) < 0;
  var done = busy($("#email-status"), needsLlm ? "Colibri traduce…" : "Generez…");
  try {
    var res = await api("/emails/draft", payload);
    $("#email-subject").value = res.subject;
    $("#email-body").value = res.body;
    $("#email-result").hidden = false;
    done(res.translated ? "Tradus de Colibri, verificat (coduri + Egress Guard)." : "Generat din șablon, verificat de Egress Guard.");
  } catch (err) {
    done((err.status === 422 ? "Blocat: " : "Eroare: ") + err.message, true);
  }
});

$("#copy-email").addEventListener("click", async function () {
  await navigator.clipboard.writeText("Subiect: " + $("#email-subject").value + "\n\n" + $("#email-body").value);
  $("#email-status").textContent = "Copiat în clipboard.";
});

// ---------- inițializare ------------------------------------------------------------

$("#offer-form").elements.offer_date.value = new Date().toISOString().slice(0, 10);
addLine();
addCert();
addEmailItem();
