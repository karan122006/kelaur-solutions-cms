/* Keluar Solutions · SFC CMS front end (Alpine.js, no build step).
   One page module per DFD Level-0 process; every call goes to the matching /api/<process> blueprint. */

const DICT = {
  en: {home:'Home', patients:'Patients', appointments:'Appointments', consult:'Consultation', pharmacy:'Pharmacy & Stock',
       billing:'Billing & Payments', claims:'Panel & Insurance Claims', reports:'Reports & Dashboard', messages:'Messages & Alerts',
       admin:'Users & Audit', signout:'Sign out', search:'Search patient by name, IC, phone or ID', welcome:'Good to see you',
       g_front:'Front desk', g_clinic:'Clinical', g_mgmt:'Management', g_sys:'System', signin:'Sign in', alerts:'Alerts'},
  ms: {home:'Utama', patients:'Pesakit', appointments:'Temu Janji', consult:'Konsultasi', pharmacy:'Farmasi & Stok',
       billing:'Bil & Bayaran', claims:'Tuntutan Panel & Insurans', reports:'Laporan & Papan Pemuka', messages:'Mesej & Amaran',
       admin:'Pengguna & Audit', signout:'Log keluar', search:'Cari pesakit melalui nama, IC, telefon atau ID', welcome:'Selamat datang',
       g_front:'Kaunter hadapan', g_clinic:'Klinikal', g_mgmt:'Pengurusan', g_sys:'Sistem', signin:'Log masuk', alerts:'Amaran'}
};

// Pages, the DFD process each one implements, who may open it, and its photo
const PAGES = [
  {id:'home', p:'', grp:'', roles:'*', img:'hero'},
  {id:'patients', p:'1.0', grp:'g_front', roles:'receptionist nurse doctor dentist pharmacy branch_manager admin', img:'family',
   sub:'Register once, find anywhere: one central record for all five branches.'},
  {id:'appointments', p:'2.0', grp:'g_front', roles:'receptionist nurse doctor dentist branch_manager', img:'phone',
   sub:'Live slot availability by branch, service and doctor. Double bookings are blocked.'},
  {id:'billing', p:'5.0', grp:'g_front', roles:'receptionist branch_manager', img:'card',
   sub:'Itemised bills straight from the visit and pharmacy records. Cash, card and e-wallet.'},
  {id:'consult', p:'3.0', grp:'g_clinic', roles:'doctor dentist nurse', img:'consult',
   sub:'Vitals, notes and prescriptions with the full cross-branch history beside you.'},
  {id:'pharmacy', p:'4.0', grp:'g_clinic', roles:'pharmacy branch_manager head_office', img:'pharmacy',
   sub:'Dispense with allergy checks, batch tracking and automatic stock deduction.'},
  {id:'claims', p:'6.0', grp:'g_mgmt', roles:'receptionist branch_manager head_office', img:'records',
   sub:'Claims prepared from billing records and tracked from draft to paid.'},
  {id:'reports', p:'7.0', grp:'g_mgmt', roles:'branch_manager head_office', img:'analytics',
   sub:'Revenue, patients, appointments, stock and claims for every branch in one view.'},
  {id:'messages', p:'8.0', grp:'g_sys', roles:'*', img:'waiting', sub:'Staff alerts and the SMS log with delivery status.'},
  {id:'admin', p:'9.0', grp:'g_sys', roles:'admin', img:'doctor', sub:'Accounts, roles and the audit log of every record access.'},
];
const DEMO = [
  ['reception.pj','Receptionist'],['nurse.pj','Nurse'],['dr.rahman','Doctor (GP)'],['dr.aminah','Dentist'],
  ['pharmacy.pj','Pharmacy assistant'],['manager.pj','Branch manager'],['hq','Head office'],['admin','Administrator']];
const ROLE_NAME = {receptionist:'Receptionist', nurse:'Nurse', doctor:'Doctor', dentist:'Dentist', pharmacy:'Pharmacy Assistant',
  branch_manager:'Branch Manager', head_office:'Head Office', admin:'Administrator'};
const SERVICES = [['General Practice','consult'],['Paediatrics','paeds'],['Dental','dental']];

const RM = v => 'RM ' + Number(v || 0).toLocaleString('en-MY', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const todayStr = (o = 0) => { const d = new Date(); d.setDate(d.getDate() + o); return d.toLocaleDateString('en-CA'); };
const fmtDT = s => s ? new Date(s.replace(' ', 'T')).toLocaleString('en-MY', {day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'}) : '';
const fmtD = s => s ? new Date(s.slice(0, 10) + 'T00:00').toLocaleDateString('en-MY', {day:'2-digit', month:'short', year:'numeric'}) : '';
const age = dob => { if (!dob) return ''; const d = new Date(dob), n = new Date(); let a = n.getFullYear() - d.getFullYear();
  if (n < new Date(n.getFullYear(), d.getMonth(), d.getDate())) a--; return a < 2 ? Math.max(0, Math.round((n - d) / 2.63e9)) + ' mo' : a + ' y'; };
const initials = n => (n || '?').replace(/^Dr\.\s*/, '').split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase();

async function api(path, opt = {}) {
  const r = await fetch('/api' + path, {method: opt.method || (opt.body ? 'POST' : 'GET'),
    headers: Object.assign({'X-Requested-With': 'SFC-CMS'}, opt.body ? {'Content-Type': 'application/json'} : {}), body: opt.body ? JSON.stringify(opt.body) : undefined,
    credentials: 'same-origin'});
  const data = r.headers.get('content-type')?.includes('json') ? await r.json() : {};
  if (r.status === 401 && path !== '/login') window.dispatchEvent(new CustomEvent('signed-out', {detail: data.error}));
  if (!r.ok) throw Object.assign(new Error(data.error || 'Something went wrong.'), {data, status: r.status});
  return data;
}

/* ---------- Tiny SVG charts (single-series, one hue, hover tooltips) ---------- */
const Chart = {
  tip(e, text) { let t = document.getElementById('tip'); if (!text) { t.hidden = true; return; }
    t.hidden = false; t.textContent = text; t.style.left = (e.clientX + 12) + 'px'; t.style.top = (e.clientY - 34) + 'px'; },
  hbars(items, fmt = v => v, vw = 1200) {   // horizontal bars: magnitude by category, direct labels
    if (!items?.length) return '<p class="muted small">No data for this filter.</p>';
    const small = vw < 600, max = Math.max(...items.map(i => i.v)) || 1, W = small ? 360 : 520, rowH = 30, L = small ? 112 : 170;
    return `<svg class="chart" viewBox="0 0 ${W} ${items.length * rowH + 4}" role="img">` + items.map((it, i) => {
      const w = Math.max(3, (W - L - 95) * it.v / max), y = i * rowH + 4;
      return `<text class="lbl" x="${L - 8}" y="${y + 15}" text-anchor="end">${esc(String(it.k).slice(0, small ? 16 : 26))}</text>
        <rect class="bar" x="${L}" y="${y + 3}" width="${w}" height="16" rx="4" data-tip="${esc(it.k)}: ${fmt(it.v)}"/>
        <text x="${L + w + 6}" y="${y + 15}" class="lbl">${fmt(it.v)}</text>`; }).join('') + '</svg>';
  },
  line(points, fmt = v => v, vw = 1200) {   // revenue over time: area + 2px line + crosshair hit areas
    if (!points?.length) return '<p class="muted small">No data for this filter.</p>';
    const W = Math.max(340, Math.min(1100, vw < 900 ? vw - 40 : vw - 330)), H = vw < 600 ? 220 : 250, P = {l: 54, r: 12, t: 12, b: 26}, max = Math.max(...points.map(p => p.v)) * 1.1 || 1;
    const x = i => P.l + (W - P.l - P.r) * (points.length === 1 ? .5 : i / (points.length - 1)), y = v => P.t + (H - P.t - P.b) * (1 - v / max);
    const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join('');
    const ticks = [0, .25, .5, .75, 1].map(f => max * f);
    const step = Math.ceil(points.length / (W < 600 ? 4 : 7)), bw = (W - P.l - P.r) / Math.max(points.length, 1);
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"><defs><linearGradient id="ga" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="#1765b0" stop-opacity=".22"/><stop offset="1" stop-color="#1765b0" stop-opacity="0"/></linearGradient></defs>
      <g class="grid">${ticks.map(t => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}"/><text x="${P.l - 8}" y="${y(t) + 4}" text-anchor="end">${Math.round(t).toLocaleString()}</text>`).join('')}</g>
      <path class="area" d="${d}L${x(points.length - 1)},${y(0)}L${x(0)},${y(0)}Z"/><path class="line" d="${d}"/>
      ${points.map((p, i) => i % step ? '' : `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${fmtD(p.d).slice(0, 6)}</text>`).join('')}
      ${points.map((p, i) => `<rect x="${x(i) - bw / 2}" y="${P.t}" width="${bw}" height="${H - P.t - P.b}" fill="transparent" data-tip="${fmtD(p.d)}: ${fmt(p.v)}" data-x="${x(i)}"/>`).join('')}
      <line id="xh" x1="0" x2="0" y1="${P.t}" y2="${H - P.b}" stroke="#0b2f5c" stroke-width="1" stroke-dasharray="3 3" opacity="0"/></svg>`;
  },
  bind(el) {
    el.onmousemove = e => { const t = e.target.closest('[data-tip]'); Chart.tip(e, t?.dataset.tip);
      const xh = el.querySelector('#xh'); if (xh) { xh.setAttribute('opacity', t?.dataset.x ? .5 : 0); if (t?.dataset.x) { xh.setAttribute('x1', t.dataset.x); xh.setAttribute('x2', t.dataset.x); } } };
    el.onmouseleave = () => Chart.tip(null);
  }
};
/* Phones: every data table turns into stacked cards. Each cell gets its column name as a label (read by CSS). */
function labelTables() {
  let queued = false;
  const run = () => { queued = false;
    document.querySelectorAll('table.tbl:not(.keep)').forEach(t => {
      const heads = [...t.querySelectorAll('thead th')].map(th => th.textContent.trim());
      t.querySelectorAll('tbody tr').forEach(tr => { let col = 0; [...tr.children].forEach(td => {
        const l = td.colSpan > 1 ? '' : (heads[col] || ''); col += td.colSpan || 1; if (td.dataset.label !== l) td.dataset.label = l; }); });
    }); };
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(run); } })
    .observe(document.body, {childList: true, subtree: true, characterData: true});
  run();
}
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])); }

function cms() {
  return {
    // ---------- shell state ----------
    user: null, page: 'home', lang: localStorage.getItem('lang') || 'en', ref: {branches: [], providers: [], doctors: []},
    toastMsg: null, toastKind: '', busy: false, idleWarn: false, lastAct: Date.now(), alerts: [], unread: 0, modal: null,
    login: {username: '', password: '', error: ''}, navOpen: false, pw: null, vw: window.innerWidth,
    demoMode: document.body.dataset.demo !== 'false', DEMO, PAGES, SERVICES, ROLE_NAME, RM, fmtDT, fmtD, age, initials, todayStr,

    t(k) { return DICT[this.lang][k] || DICT.en[k] || k; },
    setLang(l) { this.lang = l; localStorage.setItem('lang', l); },
    can(id) { const p = PAGES.find(x => x.id === id); return p && (p.roles === '*' || p.roles.split(' ').includes(this.user?.role)); },
    navPages(g) { return PAGES.filter(p => p.grp === g && this.can(p.id)); },
    pageInfo() { return PAGES.find(p => p.id === this.page) || PAGES[0]; },
    img(n) { return `/static/img/${n}.jpg`; },
    branchName(id) { return this.ref.branches.find(b => b.branch_id === id)?.branch_name || id; },
    toast(msg, kind = 'good') { this.toastMsg = msg; this.toastKind = kind; clearTimeout(this._tt); this._tt = setTimeout(() => this.toastMsg = null, 4200); },
    fail(e) { this.toast(e.message, 'bad'); },

    async init() {
      window.addEventListener('signed-out', e => { if (this.user) { sessionStorage.setItem('signoutMsg', e.detail || 'Please sign in again.'); location.reload(); } });
      ['click', 'keydown', 'mousemove'].forEach(ev => window.addEventListener(ev, () => { this.lastAct = Date.now(); this.idleWarn = false; }, {passive: true}));
      setInterval(() => this.idleTick(), 5000);
      window.addEventListener('hashchange', () => this.route());
      let rt; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { this.vw = window.innerWidth;
        if (this.vw > 900) this.navOpen = false; this.$nextTick(() => document.querySelectorAll('[data-chart]').forEach(Chart.bind)); }, 120); });
      labelTables();
      this.login.error = sessionStorage.getItem('signoutMsg') || ''; sessionStorage.removeItem('signoutMsg');
      try { const r = await api('/me'); this.user = r.user; if (r.must_change_password) this.forcePw(); await this.afterLogin(); } catch (e) { /* show login */ }
    },
    idleTick() {   // SRS 5.3.4: automatic logout after 5 minutes of inactivity
      if (!this.user) return;
      const idle = (Date.now() - this.lastAct) / 1000;
      this.idleWarn = idle > 270;
      if (idle > 300) { this.logout('You were signed out after 5 minutes of inactivity.'); }
    },
    async doLogin() {
      this.login.error = ''; this.busy = true;
      try { const r = await api('/login', {body: {username: this.login.username, password: this.login.password}});
        this.user = r.user; if (r.must_change_password) this.forcePw(this.login.password);
        this.login.password = ''; await this.afterLogin(); }
      catch (e) { this.login.error = e.message; } finally { this.busy = false; }
    },
    quick(u) { this.login.username = u; this.login.password = 'Sfc@2026'; this.doLogin(); },
    async afterLogin() {
      this.lastAct = Date.now(); this.ref = await api('/ref'); this.loadAlerts(); this.route();
      clearInterval(this._al); this._al = setInterval(() => this.user && this.loadAlerts(), 30000);
    },
    async logout(msg) {   // full reload so no patient data stays in memory after sign-out
      try { await api('/logout', {body: {}}); } catch (e) {}
      if (msg) sessionStorage.setItem('signoutMsg', msg); location.hash = ''; location.reload(); },
    async loadAlerts() { try { const r = await api('/notifications'); this.alerts = r.alerts; this.unread = r.unread; } catch (e) {} },
    go(id) { location.hash = id; },
    forcePw(cur = '') { this.pw = {current: cur, new: '', confirm: '', forced: true, err: ''}; },
    async savePw() {
      const p = this.pw; p.err = '';
      if (p.new !== p.confirm) { p.err = 'The two new passwords do not match.'; return; }
      try { const r = await api('/password', {body: {current: p.current, new: p.new}}); this.pw = null; this.toast(r.message); }
      catch (e) { p.err = e.message; }
    },
    route() {
      const id = (location.hash || '#home').slice(1).split('/')[0];
      this.page = this.can(id) ? id : 'home';
      this.navOpen = false;
      window.scrollTo(0, 0);
      const fn = {patients: 'pInit', appointments: 'aInit', consult: 'cInit', pharmacy: 'phInit', billing: 'bInit', claims: 'clInit',
                  reports: 'rInit', messages: 'mInit', admin: 'adInit', home: 'hInit'}[this.page];
      fn && this[fn]();
    },
    reveal() {   // on phones/tablets the detail panel sits below the list: bring it into view after a tap
      if (window.innerWidth > 1100) return;
      this.$nextTick(() => setTimeout(() => { const el = [...document.querySelectorAll('[data-detail]')].find(e => e.offsetParent);
        el && el.scrollIntoView({behavior: 'smooth', block: 'start'}); }, 60));
    },
    printDoc(html) { document.getElementById('print').innerHTML = html; window.print(); },
    printPage() { document.body.classList.add('print-page'); window.print(); setTimeout(() => document.body.classList.remove('print-page'), 500); },

    // ================= HOME =================
    home: {queue: [], appts: 0},
    async hInit() {
      try { if (this.can('appointments')) { const r = await api('/appointments'); this.home.appts = r.appointments.length;
        const q = await api('/queue'); this.home.queue = q.queue.filter(x => x.queue_status !== 'Done'); } } catch (e) {}
    },

    // ================= 1.0 PATIENTS =================
    pt: {q: '', results: [], msg: '', sel: null, mode: 'view', step: 1, form: {}, errs: {}, dup: null, conf: null},
    pInit() { const id = location.hash.split('/')[1]; if (id) this.pOpen(id); },
    async pSearch() {
      const q = this.pt.q.trim(); if (q.length < 2) { this.pt.results = []; this.pt.msg = ''; return; }
      const r = await api('/patients?q=' + encodeURIComponent(q)); this.pt.results = r.results; this.pt.msg = r.message || '';
    },
    async pOpen(id) { try { this.pt.sel = await api('/patients/' + id); this.pt.mode = 'view'; this.reveal(); } catch (e) { this.fail(e); } },
    pNew() { this.reveal(); this.pt.mode = 'form'; this.pt.step = 1; this.pt.errs = {}; this.pt.dup = null; this.pt.sel = null;
      this.pt.form = {full_name: '', ic_passport_no: '', date_of_birth: '', gender: '', phone: '', address: '', emergency_contact: '',
                      allergies: '', provider_id: '', policy_no: '', valid_until: '', no_allergy: false}; },
    pEdit() { const s = this.pt.sel; this.pt.mode = 'form'; this.pt.step = 1; this.pt.errs = {}; this.pt.dup = null;
      this.pt.form = {...s, provider_id: s.coverage?.provider_id || '', policy_no: s.coverage?.policy_no || '',
                      valid_until: s.coverage?.valid_until || '', no_allergy: s.allergies === 'None known'}; },
    pStepOk(n) {   // client-side validation per step mirrors process 1.1 (server re-checks everything)
      const f = this.pt.form, e = {};
      if (n === 1) { if (!f.full_name.trim()) e.full_name = 'Required';
        if (!/^(\d{6}-?\d{2}-?\d{4}|[A-Za-z]\d{6,9})$/.test(f.ic_passport_no.trim())) e.ic_passport_no = '12-digit IC (e.g. 900101-10-1234) or passport no.';
        if (!f.date_of_birth) e.date_of_birth = 'Required'; else if (f.date_of_birth > todayStr()) e.date_of_birth = 'Cannot be in the future';
        if (!f.gender) e.gender = 'Choose one'; }
      if (n === 2) { const d = (f.phone || '').replace(/\D/g, ''); if (d.length < 9 || d.length > 12) e.phone = '9–12 digits, e.g. 012-345 6789';
        if (!f.emergency_contact?.trim()) e.emergency_contact = 'Name and phone of an emergency contact'; }
      if (n === 3) { if (!f.no_allergy && !f.allergies?.trim()) e.allergies = 'Enter allergies or tick “None known”';
        if (f.provider_id && !f.policy_no?.trim()) e.policy_no = 'Policy / membership no. is required for a panel'; }
      this.pt.errs = e; return !Object.keys(e).length;
    },
    pNext() { if (this.pStepOk(this.pt.step)) this.pt.step++; },
    async pSave(confirmPossible = false) {
      const f = {...this.pt.form, allergies: this.pt.form.no_allergy ? 'None known' : this.pt.form.allergies, confirm_possible_duplicate: confirmPossible};
      this.busy = true;
      try {
        const editing = !!this.pt.form.patient_id;
        const r = await api('/patients' + (editing ? '/' + f.patient_id : ''), {method: editing ? 'PUT' : 'POST', body: f});
        this.pt.conf = r.confirmation; this.toast(editing ? 'Patient record updated.' : `Registered. Patient ID ${r.patient_id}.`);
        await this.pOpen(r.patient_id);
      } catch (e) {
        if (e.data?.fields) { this.pt.errs = e.data.fields; this.pt.step = e.data.fields.full_name || e.data.fields.ic_passport_no || e.data.fields.date_of_birth || e.data.fields.gender ? 1 : e.data.fields.phone || e.data.fields.emergency_contact ? 2 : 3; }
        if (e.data?.duplicate) this.pt.dup = e.data.duplicate; else this.fail(e);
      } finally { this.busy = false; }
    },
    pPrintConf() { const c = this.pt.conf; this.printDoc(`<div class="doc"><div class="hd"><img src="/static/img/logo.png"><div class="right"><b>Sunrise Family Clinics</b><br>Registration confirmation</div></div>
      <p>Patient ID: <b>${esc(c.patient_id)}</b><br>Name: ${esc(c.full_name)}<br>Registered at: ${esc(c.branch_name)}<br>Date: ${fmtDT(c.registration_date)}</p>
      <p class="small">This ID works at every SFC branch in Petaling Jaya, Shah Alam and Subang Jaya.</p></div>`); },

    // ================= 2.0 APPOINTMENTS =================
    ap: {tab: 'book', service: 'General Practice', branch: '', date: todayStr(1), doctors: [], pick: null, pq: '', presults: [], patient: null,
         list: [], listDate: todayStr(), queue: [], sched: {staff: [], schedule: []}, schedFrom: todayStr(), sForm: null, resch: null},
    async aInit() { this.ap.branch = this.user.branch_id; if (this.user.role !== 'receptionist') this.ap.tab = this.user.role === 'branch_manager' ? 'schedule' : 'list';
      this.aLoadTab(); clearInterval(this._qi); this._qi = setInterval(() => this.page === 'appointments' && this.ap.tab === 'queue' && this.aQueue(), 15000); },
    aLoadTab() { ({book: 'aSlots', list: 'aList', queue: 'aQueue', schedule: 'aSched'})[this.ap.tab] && this[({book: 'aSlots', list: 'aList', queue: 'aQueue', schedule: 'aSched'})[this.ap.tab]](); },
    async aSlots() { this.ap.pick = null; try { this.ap.doctors = (await api(`/slots?branch_id=${this.ap.branch}&service=${encodeURIComponent(this.ap.service)}&date=${this.ap.date}`)).doctors; } catch (e) { this.fail(e); } },
    async aFindPatient() { const q = this.ap.pq.trim(); if (q.length < 2) { this.ap.presults = []; return; }
      this.ap.presults = (await api('/patients?q=' + encodeURIComponent(q))).results; },
    async aBook() {
      if (!this.ap.patient || !this.ap.pick) return this.toast('Choose a patient and a free slot first.', 'bad');
      this.busy = true;
      try { const r = await api('/appointments', {body: {patient_id: this.ap.patient.patient_id, staff_id: this.ap.pick.staff_id, branch_id: this.ap.branch,
          service_type: this.ap.service, appointment_datetime: this.ap.pick.datetime, booking_type: 'Phone', reschedule_of: this.ap.resch?.appointment_id}});
        this.toast(r.message); this.ap.resch = null; this.ap.patient = null; this.ap.pq = ''; this.aSlots(); }
      catch (e) { this.fail(e); this.aSlots(); } finally { this.busy = false; }
    },
    async aWalkin() {
      if (!this.ap.patient) return this.toast('Find the patient first (or register them on the Patients page).', 'bad');
      try { const r = await api('/walkin', {body: {patient_id: this.ap.patient.patient_id, service_type: this.ap.service}});
        this.toast(r.message); this.ap.patient = null; this.ap.pq = ''; this.ap.tab = 'queue'; this.aQueue(); } catch (e) { this.fail(e); }
    },
    async aList() { try { this.ap.list = (await api(`/appointments?date=${this.ap.listDate}`)).appointments; } catch (e) { this.fail(e); } },
    async aCheckin(a) { try { const r = await api(`/appointments/${a.appointment_id}/checkin`, {body: {}}); this.toast(r.message); this.aList(); } catch (e) { this.fail(e); } },
    aCancel(a) { this.modal = {title: 'Cancel appointment?', text: `Cancel ${a.full_name}'s appointment at ${fmtDT(a.appointment_datetime)}? The patient will get an SMS.`,
      ok: 'Cancel appointment', danger: true, run: async () => { const r = await api(`/appointments/${a.appointment_id}/cancel`, {body: {}}); this.toast(r.message); this.aList(); }}; },
    aReschedule(a) { this.ap.resch = a; this.ap.patient = {patient_id: a.patient_id, full_name: a.full_name}; this.ap.service = a.service_type;
      this.ap.date = a.appointment_datetime.slice(0, 10); this.ap.tab = 'book'; this.aSlots(); },
    async aQueue() { try { this.ap.queue = (await api('/queue')).queue; } catch (e) {} },
    lane(s) { return this.ap.queue.filter(q => q.queue_status === s); },
    async aSched() { try { this.ap.sched = await api(`/schedules?from=${this.ap.schedFrom}`); } catch (e) { this.fail(e); } },
    schedDays() { return [...Array(7)].map((_, i) => { const d = new Date(this.ap.schedFrom + 'T00:00'); d.setDate(d.getDate() + i); return d.toLocaleDateString('en-CA'); }); },
    schedCell(sid, d) { return this.ap.sched.schedule.find(s => s.staff_id === sid && s.work_date === d); },
    async aSaveSched() {
      try { const r = await api('/schedules', {body: this.ap.sForm}); this.toast(r.message, r.message.includes('Note') ? '' : 'good'); this.ap.sForm = null; this.aSched(); }
      catch (e) { this.fail(e); }
    },
    async aReminders() { try { this.toast((await api('/reminders/run', {body: {}})).message); } catch (e) { this.fail(e); } },

    // ================= 3.0 CONSULTATION =================
    cs: {queue: [], procs: [], open: null, vit: {temp: '', bp: '', pulse: '', weight: ''}, notes: {}, rx: [], procSel: [], errs: {}, allergyHit: null, showDone: false},
    async cInit() { try { const r = await api('/consult/queue'); this.cs.queue = r.queue; this.cs.procs = r.procedures; } catch (e) { this.fail(e); } },
    cQueue() { return this.cs.queue.filter(q => this.cs.showDone || !['Done', 'Paying', 'At Pharmacy'].includes(q.queue_status)); },
    async cOpen(q) {
      try { this.cs.open = await api('/consult/' + q.queue_id); const v = this.cs.open.consultation.vitals || {};
        this.cs.vit = {temp: v.temp || '', bp: v.bp || '', pulse: v.pulse || '', weight: v.weight || ''};
        this.cs.notes = {symptoms: '', diagnosis: '', treatment: '', follow_up_date: ''}; this.cs.rx = []; this.cs.procSel = []; this.cs.errs = {}; this.cs.allergyHit = null;
        this.cInit(); this.reveal(); } catch (e) { this.fail(e); }
    },
    async cVitals() { try { const r = await api(`/consult/${this.cs.open.queue.queue_id}/vitals`, {body: this.cs.vit}); this.toast(r.message); this.cInit(); this.cs.open = null; } catch (e) { this.fail(e); } },
    cAddRx() { this.cs.rx.push({medication_id: '', dosage: '', quantity: 1}); },
    cTotal() { const o = this.cs.open; if (!o) return 0; let t = o.fee + this.cs.procSel.reduce((s, d) => s + (this.cs.procs.find(p => p.description === d)?.unit_price || 0), 0);
      this.cs.rx.forEach(r => { const m = o.medications.find(m => m.medication_id === r.medication_id); if (m) t += m.unit_price * (+r.quantity || 0); }); return t; },
    async cComplete(override = false) {
      this.busy = true;
      try { const r = await api(`/consult/${this.cs.open.queue.queue_id}/complete`, {body: {...this.cs.notes, procedures: this.cs.procSel, prescription: this.cs.rx, override_allergy: override}});
        this.toast(r.message); this.cs.open = null; this.cInit(); }
      catch (e) { if (e.data?.allergy) this.cs.allergyHit = e.message; else { this.cs.errs = e.data?.fields || {}; this.fail(e); } }
      finally { this.busy = false; }
    },
    async cStatus(q, s) { try { await api(`/consult/${q.queue_id}/status`, {body: {status: s}}); this.cInit(); } catch (e) { this.fail(e); } },

    // ================= 4.0 PHARMACY & STOCK =================
    ph: {tab: 'queue', rx: [], open: null, checked: false, labels: null, stock: {medications: [], batches: [], suppliers: [], transfers: []},
         net: {cells: [], branches: []}, recv: null, adj: null, tr: null, filter: '', branch: ''},
    async phInit() { this.ph.branch = this.user.branch_id; if (this.user.role !== 'pharmacy') this.ph.tab = this.user.role === 'head_office' ? 'network' : 'stock'; this.phLoad(); },
    phLoad() { ({queue: 'phQueue', stock: 'phStock', network: 'phNet', transfers: 'phStock'})[this.ph.tab] && this[({queue: 'phQueue', stock: 'phStock', network: 'phNet', transfers: 'phStock'})[this.ph.tab]](); },
    async phQueue() { try { this.ph.rx = (await api('/pharmacy/queue')).prescriptions; } catch (e) { this.fail(e); } },
    phOpen(r) { this.ph.open = JSON.parse(JSON.stringify(r)); this.ph.checked = false; this.ph.labels = null;
      this.ph.open.items.forEach(i => i.batch_id = i.batches[0]?.batch_id || ''); this.reveal(); },
    async phDispense() {
      this.busy = true;
      try { const r = await api('/pharmacy/dispense/' + this.ph.open.prescription_id, {body: {allergy_checked: this.ph.checked,
          items: this.ph.open.items.map(i => ({item_id: i.item_id, batch_id: i.batch_id}))}});
        this.toast(r.message); this.ph.labels = r.labels; this.phQueue(); this.loadAlerts(); }
      catch (e) { this.fail(e); } finally { this.busy = false; }
    },
    phPrintLabels() { this.printDoc(this.ph.labels.map(l => `<div class="label"><div class="small">${esc(l.branch_name)} · ${esc(l.phone)}</div>
      <div class="med">${esc(l.medication_name)}</div><div><b>${esc(l.dosage || '')}</b></div><div>Qty: ${l.quantity} ${esc(l.unit)}</div>
      <div class="small">For: ${esc(l.full_name)} (${esc(l.patient_id)})<br>Dr: ${esc(l.doctor)} · ${fmtD(l.issued_at)}<br>Batch ${esc(l.batch_no)} · Exp ${fmtD(l.expiry_date)}</div></div>`).join('')); },
    async phStock() { try { this.ph.stock = await api('/stock?branch_id=' + (this.ph.branch || '')); } catch (e) { this.fail(e); } },
    phMeds() { const f = this.ph.filter.toLowerCase(); return this.ph.stock.medications.filter(m => !f || m.medication_name.toLowerCase().includes(f)); },
    async phNet() { try { this.ph.net = await api('/stock/network'); } catch (e) { this.fail(e); } },
    netRows() { const by = {}; this.ph.net.cells.forEach(c => { (by[c.medication_id] ||= {name: c.medication_name, lvl: c.reorder_level, cells: {}}).cells[c.branch_id] = c; }); return Object.values(by); },
    heat(c, lvl) { const r = c.qty / (lvl || 1); return r <= 1 ? 'background:#fdecea;color:#c0362c;font-weight:700' : r > 4 ? 'background:#dbe9f7' : r > 2 ? 'background:#eaf2fb' : ''; },
    async phSubmit(kind) {
      const path = {recv: '/stock/receive', adj: '/stock/adjust', tr: '/stock/transfer'}[kind];
      try { const r = await api(path, {body: this.ph[kind]}); this.toast(r.message); this.ph[kind] = null; this.phStock(); this.loadAlerts(); } catch (e) { this.fail(e); }
    },
    async phDecide(t, d) { try { const r = await api(`/stock/transfer/${t.transfer_id}/${d}`, {body: {}}); this.toast(r.message); this.phStock(); } catch (e) { this.fail(e); } },

    // ================= 5.0 BILLING =================
    bl: {pending: [], bills: [], bill: null, pay: {payment_method: 'Cash', amount: '', reference_no: '', tendered: ''}, receipt: null},
    async bInit() { try { const r = await api('/billing/ready'); this.bl.pending = r.pending; this.bl.bills = r.bills; } catch (e) { this.fail(e); } },
    async bGenerate(p) { try { const r = await api('/billing/generate/' + p.consultation_id, {body: {}}); this.bShow(r.bill); this.bInit(); } catch (e) { this.fail(e); } },
    async bOpen(b) { try { this.bShow(await api('/billing/' + b.bill_id)); } catch (e) { this.fail(e); } },
    bShow(b) { this.reveal(); this.bl.bill = b; this.bl.receipt = null; this.bl.pay = {payment_method: 'Cash', amount: b.outstanding_balance.toFixed(2), reference_no: '', tendered: ''}; },
    async bPay() {
      this.busy = true;
      try { const r = await api(`/billing/${this.bl.bill.bill_id}/pay`, {body: this.bl.pay}); this.toast(r.message);
        this.bl.receipt = r.receipt_no; this.bShow(r.bill); this.bl.receipt = r.receipt_no; this.bInit(); }
      catch (e) { this.fail(e); } finally { this.busy = false; }
    },
    bPrint() { const b = this.bl.bill, p = b.payments.at(-1);
      this.printDoc(`<div class="doc" style="max-width:420px"><div class="hd"><img src="/static/img/logo.png"><div class="right small"><b>${esc(b.branch_name)}</b><br>${esc(b.address)}<br>${esc(b.branch_phone)}</div></div>
      <div class="row between"><b>OFFICIAL RECEIPT</b><span>${esc(p?.receipt_no || '')}</span></div><p class="small">Bill ${esc(b.bill_id)} · ${fmtDT(p?.receipt_issued_at || b.bill_date)}<br>Patient: ${esc(b.full_name)}</p>
      <table class="tbl">${b.items.map(i => `<tr><td>${esc(i.description)} × ${i.quantity}</td><td class="num">${RM(i.amount)}</td></tr>`).join('')}
      <tr><td><b>Total</b></td><td class="num"><b>${RM(b.total_amount)}</b></td></tr>${b.panel_share ? `<tr><td>Billed to ${esc(b.coverage?.provider_name)}</td><td class="num">−${RM(b.panel_share)}</td></tr>` : ''}
      ${b.payments.map(y => `<tr><td>Paid · ${esc(y.payment_method)} ${esc(y.reference_no || '')}</td><td class="num">${RM(y.amount)}</td></tr>`).join('')}
      <tr><td><b>Balance</b></td><td class="num"><b>${RM(b.outstanding_balance)}</b></td></tr></table><p class="small center">Thank you. Get well soon.</p></div>`); },
    change() { const t = parseFloat(this.bl.pay.tendered), a = parseFloat(this.bl.pay.amount); return t > a ? t - a : 0; },

    // ================= 6.0 CLAIMS =================
    cl: {claims: [], summary: [], providers: [], unclaimed: 0, status: 'all', selected: [], dec: null, prov: null},
    async clInit() { try { Object.assign(this.cl, await api('/claims')); this.cl.selected = []; } catch (e) { this.fail(e); } },
    clList() { return this.cl.claims.filter(c => this.cl.status === 'all' || (this.cl.status === 'flag' ? c.flag : c.claim_status === this.cl.status)); },
    clCount(s) { return this.cl.claims.filter(c => c.claim_status === s).length; },
    async clGenerate() { try { this.toast((await api('/claims/generate', {body: {}})).message); this.clInit(); } catch (e) { this.fail(e); } },
    async clSubmit() { if (!this.cl.selected.length) return this.toast('Tick the draft claims to submit.', 'bad');
      try { this.toast((await api('/claims/submit', {body: {ids: this.cl.selected}})).message); this.clInit(); } catch (e) { this.fail(e); } },
    async clDecide() { try { const r = await api(`/claims/${this.cl.dec.claim_id}/decision`, {body: this.cl.dec}); this.toast(r.message); this.cl.dec = null; this.clInit(); this.loadAlerts(); } catch (e) { this.fail(e); } },
    async clResubmit(c) { try { this.toast((await api(`/claims/${c.claim_id}/resubmit`, {body: {}})).message); this.clInit(); } catch (e) { this.fail(e); } },
    async clSaveProv() { try { const r = await api('/providers/' + this.cl.prov.provider_id, {method: 'PUT', body: this.cl.prov}); this.toast(r.message); this.cl.prov = null; this.clInit(); } catch (e) { this.fail(e); } },
    statusPill(s) { return {Paid: 'good', Approved: 'teal', Rejected: 'bad', Submitted: '', Draft: 'warn', 'Partially Paid': 'warn', Unpaid: 'bad'}[s] ?? ''; },

    // ================= 7.0 REPORTS =================
    rp: {f: {branch_id: '', from: todayStr(-29), to: todayStr(), service: ''}, d: null, view: 'chart'},
    async rInit() { if (!this.rp.f.branch_id) this.rp.f.branch_id = this.user.role === 'head_office' ? 'ALL' : this.user.branch_id; this.rLoad(); },
    async rLoad() { try { const q = new URLSearchParams(this.rp.f).toString(); this.rp.d = await api('/reports/dashboard?' + q);
        this.$nextTick(() => document.querySelectorAll('[data-chart]').forEach(Chart.bind)); } catch (e) { this.fail(e); } },
    rPreset(days) { this.rp.f.from = todayStr(-days + 1); this.rp.f.to = todayStr(); this.rLoad(); },
    rExport(k) { location.href = `/api/reports/export/${k}?` + new URLSearchParams(this.rp.f); },
    chartLine() { return Chart.line(this.rp.d?.by_day, RM, this.vw); },
    chartBranch() { return Chart.hbars((this.rp.d?.by_branch || []).map(b => ({k: b.branch_name.replace('SFC ', ''), v: b.billed})), v => this.vw < 600 ? 'RM ' + Math.round(v / 1000) + 'k' : RM(v), this.vw); },
    chartSvc() { return Chart.hbars(this.rp.d?.by_service || [], v => v, this.vw); },
    chartWork() { return Chart.hbars((this.rp.d?.workload || []).map(w => ({k: w.k, v: w.v})), v => v, this.vw); },
    chartClaims() { const order = ['Draft', 'Submitted', 'Approved', 'Paid', 'Rejected'];
      return Chart.hbars(order.map(k => ({k, v: this.rp.d?.claims.find(c => c.k === k)?.v || 0})), v => v, this.vw); },

    // ================= 8.0 MESSAGES =================
    ms: {sms: []},
    async mInit() { await this.loadAlerts(); try { this.ms.sms = (await api('/notifications/sms')).log; } catch (e) {}
      if (this.unread) { await api('/notifications/read', {body: {}}); setTimeout(() => this.unread = 0, 1500); } },

    // ================= 9.0 ADMIN =================
    ad: {tab: 'users', users: [], roles: [], log: [], q: '', form: null},
    async adInit() { try { Object.assign(this.ad, await api('/users')); this.adAudit(); } catch (e) { this.fail(e); } },
    async adAudit() { try { this.ad.log = (await api('/audit?q=' + encodeURIComponent(this.ad.q))).log; } catch (e) {} },
    adNew() { this.ad.form = {full_name: '', role: 'receptionist', branch_id: 'B01', username: '', password: '', specialisation: '', isNew: true}; },
    adEdit(u) { this.ad.form = {...u, isNew: false}; },
    async adSave() {
      const f = this.ad.form;
      try { const r = f.isNew ? await api('/users', {body: f}) : await api('/users/' + f.user_id, {method: 'PUT', body: f}); this.toast(r.message); this.ad.form = null; this.adInit(); }
      catch (e) { this.fail(e); }
    },
    adReset(u) { this.modal = {title: 'Reset password?', text: `Issue a temporary password for ${u.username}?`, ok: 'Reset password',
      run: async () => { const r = await api(`/users/${u.user_id}/reset`, {body: {}}); this.modal = {title: 'Temporary password', text: r.message, ok: 'Done', run: async () => {}}; return 'keep'; }}; },

    async runModal() { const m = this.modal; try { const k = await m.run(); if (k !== 'keep') this.modal = null; } catch (e) { this.fail(e); this.modal = null; } },
  };
}
