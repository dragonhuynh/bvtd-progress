const window = {__D: {}}; const document = {getElementById: ()=>({value:"",style:{},textContent:""}), querySelectorAll: ()=>[], querySelector: ()=>null}; const localStorage = {getItem:()=>null, setItem:()=>{}, removeItem:()=>{}}; const sessionStorage = {getItem:()=>null, setItem:()=>{}, removeItem:()={}};
const D = window.__D;

// ── Auth configuration ─────────────────────────────────────────────────────────
const PASS = 'bvtd@cs2';
// depts: null = xem tất cả; array = chỉ xem phòng ban trong list
const USERS = {
  'BGD':      null,
  'HCQT':     ['HCQT'],
  'KHTH':     ['KHTH'],
  'CNTT':     ['CNTT'],
  'KSNK':     ['KSNK'],
  'CSKH':     ['CSKH'],
  'CTXH':     ['CTXH'],
  'VTTBYT':   ['VTTBYT'],
  'XN':       ['XN'],
  'TCCB':     ['TCCB'],
  'TCKT':     ['TCKT'],
  'DD':       ['Điều dưỡng', 'Công Đoàn', 'CSKH', 'Đoàn Thanh Niên'],
  'GMHS':     ['GMHS'],
  'DUOC':     ['Dược'],
  'QLCL':     ['QLCL'],
  'CONGDOAN': ['Công Đoàn'],
  'DTN':      ['Đoàn Thanh Niên'],
  'KCC':      ['K.Cấp cứu'],
  'YHCT':     ['YHCT'],
  'PHCN':     ['K.PHCN'],
  'KNOI':     ['K.Nội'],
  'KNGOAI':   ['K.Ngoại'],
};

let AUTH = null;

function doLogin() {
  const user = (document.getElementById('login-user').value || '').trim().toUpperCase();
  const pass  = document.getElementById('login-pass').value || '';
  const errEl = document.getElementById('login-err');
  if (!(user in USERS) || pass !== PASS) {
    errEl.style.display = 'block';
    document.getElementById('login-pass').value = '';
    return;
  }
  errEl.style.display = 'none';
  AUTH = { user, depts: USERS[user] };
  const remember = document.getElementById('login-remember').checked;
  if (remember) {
    localStorage.setItem('bvtd_auth', JSON.stringify(AUTH));
    sessionStorage.removeItem('bvtd_auth');
  } else {
    sessionStorage.setItem('bvtd_auth', JSON.stringify(AUTH));
    localStorage.removeItem('bvtd_auth');
  }
  document.getElementById('login-overlay').style.display = 'none';
  document.getElementById('app-body').style.display = 'flex';
  document.getElementById('user-badge').textContent = AUTH.user;
  initApp();
}

function doLogout() {
  sessionStorage.removeItem('bvtd_auth');
  localStorage.removeItem('bvtd_auth');
  AUTH = null;
  chartsInited = false; tasksRendered = false;
  window._myTasks = null; window._myStats = null;
  const deptFilter = document.getElementById('filter-dept');
  while (deptFilter.options.length > 1) deptFilter.remove(1);
  document.getElementById('app-body').style.display = 'none';
  document.getElementById('login-overlay').style.display = 'flex';
  document.getElementById('login-user').value = '';
  document.getElementById('login-pass').value = '';
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function fmtDate(s) {
  if (!s) return '—';
  const p = s.split('-');
  return p.length === 3 ? p[2]+'/'+p[1]+'/'+p[0] : s;
}

const AC = ['#4299e1','#48bb78','#ed8936','#9f7aea','#f56565','#38b2ac','#667eea','#fc8181','#68d391','#63b3ed','#b794f4','#fbb6ce'];
function avatarColor(name) {
  let h = 0;
  for (let c of name) h = (h * 31 + c.charCodeAt(0)) % AC.length;
  return AC[Math.abs(h) % AC.length];
}

function statusPill(tt) {
  if (tt === 'da_hoan_thanh')  return '<span class="status-pill status-done">✅ Hoàn thành</span>';
  if (tt === 'dang_thuc_hien') return '<span class="status-pill status-active">🔄 Đang thực hiện</span>';
  return '<span class="status-pill status-late">⚠️ Trễ deadline</span>';
}

function nhomLabel(n) {
  if (n === 'hanh_chanh')   return '🏢 Hành chính';
  if (n === 'chuyen_mon')   return '🔬 Chuyên môn';
  return '📋 Quản lý khác';
}

// ── Task filtering ─────────────────────────────────────────────────────────────
function getMyTasks() {
  if (!AUTH || !AUTH.depts) return D.tasks;
  return D.tasks.filter(t => {
    // Check phong_chinh (normalized in tasks_slim)
    if (AUTH.depts.some(d => t.phong === d)) return true;
    // Check phong_phoi_hop (raw, comma-separated)
    if (t.phoi_hop) {
      const parts = t.phoi_hop.split(', ').map(p => p.trim());
      if (parts.some(p => AUTH.depts.includes(p))) return true;
    }
    return false;
  });
}

// ── Stats computation from tasks ──────────────────────────────────────────────
function computeFromTasks(tasks) {
  const done   = tasks.filter(t => t.tt === 'da_hoan_thanh').length;
  const active = tasks.filter(t => t.tt === 'dang_thuc_hien').length;
  const late   = tasks.filter(t => t.tt === 'tre_deadline').length;
  const rate   = tasks.length ? Math.round(done / tasks.length * 100) : 0;

  // Dept breakdown
  const dm = {};
  tasks.forEach(t => {
    const d = t.phong || 'Khác';
    if (!dm[d]) dm[d] = {total:0,done:0,active:0,late:0};
    dm[d].total++;
    if (t.tt === 'da_hoan_thanh') dm[d].done++;
    else if (t.tt === 'dang_thuc_hien') dm[d].active++;
    else dm[d].late++;
  });
  const dept = Object.entries(dm).map(([k,v]) => ({name:k,...v})).sort((a,b) => b.total-a.total);

  // Monthly (last 8 months)
  const mm = {};
  tasks.forEach(t => {
    if (t.bat_dau && t.bat_dau.length >= 7) {
      const m = t.bat_dau.slice(0,7);
      mm[m] = (mm[m]||0) + 1;
    }
  });
  const months = Object.keys(mm).sort().slice(-8);

  // Nhom
  const nhom = {hanh_chanh:0, chuyen_mon:0, quan_ly_khac:0};
  tasks.forEach(t => { nhom[t.nhom||'quan_ly_khac']++; });

  // Urgent (late, sorted by deadline)
  const urgent = tasks.filter(t => t.tt === 'tre_deadline')
    .sort((a,b) => (a.ket_thuc||'9999').localeCompare(b.ket_thuc||'9999')).slice(0,20);

  // Repeats (nhac >= 2)
  const repeats = tasks.filter(t => parseInt(t.nhac||'1') >= 2)
    .sort((a,b) => parseInt(b.nhac||'1') - parseInt(a.nhac||'1'));

  return {total:tasks.length, done, active, late, rate, dept,
          months, monthly_counts: months.map(m => mm[m]),
          nhom, urgent, repeats};
}

// ── App init (called after login) ─────────────────────────────────────────────
function initApp() {
  tasksRendered = false;
  const _tn = document.getElementById('tasks-by-nhom'); if (_tn) _tn.innerHTML = '';

  const tasks = getMyTasks();
  const st    = computeFromTasks(tasks);
  window._myTasks = tasks;
  window._myStats = st;

  // Static labels
  document.getElementById('today-label').textContent = D.today_vn || D.today;
  document.getElementById('gen-label').textContent   = 'Cập nhật: ' + D.generated;
  const _verEl = document.getElementById('ver-label');
  if (_verEl && D.version) _verEl.textContent = 'v' + D.version;

  // KPI cards
  document.getElementById('s-total').textContent   = st.total;
  document.getElementById('s-done').textContent    = st.done;
  document.getElementById('s-active').textContent  = st.active;
  document.getElementById('s-late').textContent    = st.late;
  document.getElementById('s-rate').textContent    = st.rate + '%';
  document.getElementById('urgent-count-badge').textContent = st.late;

  // Urgent list
  const urgentEl = document.getElementById('urgent-list');
  if (!st.urgent.length) {
    urgentEl.innerHTML = '<li class="no-data">Không có đầu việc trễ hạn 🎉</li>';
  } else {
    urgentEl.innerHTML = st.urgent.map(t => `
        <li class="urgent-item">
          <div class="urgent-body">
            <span class="urgent-id">${t.id}</span>
            <div class="urgent-ten">${t.ten}</div>
            <div class="urgent-phong">${t.phong}</div>
          </div>
          <div class="urgent-right">
            ${t.ket_thuc ? `<div class="date-badge red">${fmtDate(t.ket_thuc)}</div>` : ''}
            ${parseInt(t.nhac)>=2 ? `<div class="nhac-badge">🔁 ${t.nhac}x</div>` : ''}
          </div>
        </li>`).join('');
  }

  // Repeat preview (all items — tab removed, this is the only view)
  const repEl = document.getElementById('repeat-preview-list');
  const repBadge = document.getElementById('repeats-count-badge');
  if (!st.repeats.length) {
    repEl.innerHTML = '<li class="no-data">Không có nhiệm vụ nào nhắc lại.</li>';
    if (repBadge) repBadge.textContent = '';
  } else {
    if (repBadge) repBadge.textContent = st.repeats.length + ' nhiệm vụ';
    repEl.innerHTML = st.repeats.map(t => {
      const bbs = t.cac_bien_ban || [];
      const tipLines = ['🔁 Nhắc ' + t.nhac + ' lần qua các biên bản:']
        .concat(bbs.map(b => '  • ' + b));
      if (t.ket_thuc) tipLines.push('📅 Deadline: ' + fmtDate(t.ket_thuc));
      if (t.last_reminder) tipLines.push('⚠ Ngày HT không được trước: ' + fmtDate(t.last_reminder));
      const tip = tipLines.join('\n').replace(/"/g, '&quot;');
      return `
        <li class="urgent-item">
          <div class="urgent-body">
            <span class="urgent-id">${t.id}</span>
            <div class="urgent-ten" title="${tip}" style="cursor:help;">${t.ten}</div>
            <div class="urgent-phong">${t.phong}</div>
          </div>
          <div class="urgent-right">
            <span class="nhac-badge">🔁 ${t.nhac}x nhắc</span>
            ${statusPill(t.tt)}
          </div>
        </li>`;
    }).join('');
  }

  // Dept progress bars
  const deptEl = document.getElementById('dept-breakdown');
  deptEl.innerHTML = st.dept.map(d => {
    const dP = d.total ? Math.round(d.done/d.total*100) : 0;
    const aP = d.total ? Math.round(d.active/d.total*100) : 0;
    const lP = d.total ? Math.round(d.late/d.total*100) : 0;
    return `
      <div class="dept-progress-row">
        <div class="dp-name" title="${d.name}">${d.name}</div>
        <div class="dp-bar-wrap">
          <div class="dp-bar-done"   style="width:${dP}%"></div>
          <div class="dp-bar-active" style="width:${aP}%"></div>
          <div class="dp-bar-late"   style="width:${lP}%"></div>
        </div>
        <div class="dp-stats">
          <span style="color:var(--green)">${d.done}✓</span>&nbsp;
          <span style="color:var(--blue)">${d.active}⟳</span>&nbsp;
          <span style="color:var(--red)">${d.late}⚠</span>&nbsp;
          <span style="color:var(--muted)">/${d.total}</span>
        </div>
      </div>`;
  }).join('');

  // Sources grid (always full — shows all biên bản regardless of user)
  const srcEl = document.getElementById('sources-grid');
  const srcLabelEl = document.getElementById('src-count-label');
  if (!D.sources.length) {
    srcEl.innerHTML = '<p style="color:var(--muted);font-size:13px;">Chưa có dữ liệu.</p>';
  } else {
    const srcTotal = D.sources.reduce((s,x) => s+x.count, 0);
    if (srcLabelEl) srcLabelEl.textContent = D.sources.length + ' biên bản · ' + srcTotal + ' đầu việc';
    srcEl.innerHTML = D.sources.map(s => {
      const hasPdf = !!s.pdf;
      const pdfPath = hasPdf ? 'bien-ban-da-ky/' + encodeURIComponent(s.pdf) : '';
      const clickAttr = hasPdf ? `onclick="window.open('${pdfPath}','_blank')" title="Nhấn để xem biên bản PDF"` : '';
      const pdfIcon = hasPdf
        ? '<div class="source-pdf-icon">📄 Xem PDF</div>'
        : '<div class="source-no-pdf">Chưa có file</div>';
      return `
        <div class="source-card${hasPdf ? ' clickable' : ''}" ${clickAttr}>
          <div class="source-name">${s.name || ('Biên bản ' + fmtDate(s.date))}</div>
          <div class="source-count">${s.count}</div>
          <div class="source-date">đầu việc</div>
          ${pdfIcon}
        </div>`;
    }).join('');
  }

  // BGĐ: show review nav + badge
  updateNavBadge();

  // Init charts
  setTimeout(() => initCharts(st), 100);
}

// ── Charts ─────────────────────────────────────────────────────────────────────
let chartsInited = false;
let _monthlyChart = null, _nhomChart = null;

function initCharts(st) {
  if (typeof Chart === 'undefined') return;
  const mn = ['','T1','T2','T3','T4','T5','T6','T7','T8','T9','T10','T11','T12'];
  const monthLabels = st.months.map(m => { const [y,mo]=m.split('-'); return mn[parseInt(mo)]+'/'+y.slice(2); });

  if (chartsInited) {
    if (_monthlyChart) { _monthlyChart.data.labels = monthLabels; _monthlyChart.data.datasets[0].data = st.monthly_counts; _monthlyChart.update(); }
    if (_nhomChart)    { _nhomChart.data.datasets[0].data = [st.nhom.hanh_chanh||0, st.nhom.chuyen_mon||0, st.nhom.quan_ly_khac||0]; _nhomChart.update(); }
    return;
  }
  chartsInited = true;

  const mCtx = document.getElementById('monthly-chart').getContext('2d');
  _monthlyChart = new Chart(mCtx, {
    type: 'bar',
    data: { labels: monthLabels, datasets: [{ label:'Đầu việc mới', data:st.monthly_counts, backgroundColor:'#f47c3c', borderRadius:7, borderSkipped:false }] },
    options: { responsive:true, plugins:{legend:{display:false}}, scales:{ y:{beginAtZero:true,grid:{color:'#f0f0f0'},ticks:{stepSize:20}}, x:{grid:{display:false}} } }
  });

  const nCtx = document.getElementById('nhom-chart').getContext('2d');
  _nhomChart = new Chart(nCtx, {
    type: 'doughnut',
    data: { labels:['Hành chính','Chuyên môn','Quản lý khác'], datasets:[{ data:[st.nhom.hanh_chanh||0,st.nhom.chuyen_mon||0,st.nhom.quan_ly_khac||0], backgroundColor:['#ed8936','#9f7aea','#4299e1'], borderWidth:3, borderColor:'#fff' }] },
    options: { responsive:true, plugins:{legend:{position:'bottom',labels:{padding:16,font:{size:12}}}} }
  });
}

// ── Tasks view (grouped by nhom → then dept) ───────────────────────────────────
let tasksRendered = false;

const NHOM_GROUPS = [
  { key: 'hanh_chanh',   label: '🏢 Hành Chính Quản Trị & VTTBYT' },
  { key: 'chuyen_mon',   label: '🔬 Chuyên Môn' },
  { key: 'quan_ly_khac', label: '📋 Quản Lý Khác' },
];

function buildTasksView(filtered) {
  const container = document.getElementById('tasks-by-nhom');
  container.innerHTML = '';

  if (!filtered.length) {
    container.innerHTML = '<div class="no-tasks-msg">Không tìm thấy đầu việc nào.</div>';
    document.getElementById('tasks-count-label').textContent = '0 đầu việc';
    return;
  }

  let totalDepts = new Set();
  const parts = [];

  NHOM_GROUPS.forEach(nhomG => {
    const nhomTasks = filtered.filter(t => t.nhom === nhomG.key);
    if (!nhomTasks.length) return;

    const nhomDone   = nhomTasks.filter(t => t.tt === 'da_hoan_thanh').length;
    const nhomActive = nhomTasks.filter(t => t.tt === 'dang_thuc_hien').length;
    const nhomLate   = nhomTasks.filter(t => t.tt === 'tre_deadline').length;

    parts.push(`
      <div class="nhom-section-header">
        <span class="nhom-label">${nhomG.label}</span>
        <div class="dept-badges">
          ${nhomDone   ? `<span class="badge badge-green">${nhomDone} xong</span>` : ''}
          ${nhomActive ? `<span class="badge badge-blue">${nhomActive} đang</span>` : ''}
          ${nhomLate   ? `<span class="badge badge-red">${nhomLate} trễ</span>` : ''}
          <span class="badge" style="background:rgba(255,255,255,.15);color:#fff">${nhomTasks.length} task</span>
        </div>
      </div>`);

    const byDept = {};
    nhomTasks.forEach(t => {
      const d = t.phong || 'Khác';
      totalDepts.add(d);
      if (!byDept[d]) byDept[d] = [];
      byDept[d].push(t);
    });

    const depts = Object.keys(byDept).sort((a,b) => byDept[b].length - byDept[a].length);
    const _pendingIds = new Set(lsGet(PK).filter(p => p.user === AUTH.user).map(p => p.id));

    depts.forEach((dept, idx) => {
      const tasks  = byDept[dept];
      const done   = tasks.filter(t => t.tt === 'da_hoan_thanh').length;
      const active = tasks.filter(t => t.tt === 'dang_thuc_hien').length;
      const late   = tasks.filter(t => t.tt === 'tre_deadline').length;
      const uid    = 'ds_' + nhomG.key + '_' + idx;
      const color  = avatarColor(dept);
      const rows = tasks.map(t => {
        const nguonShort = t.nguon ? t.nguon.replace(/^Biên bản /, '') : '—';
        const canUpd = AUTH && (t.tt === 'tre_deadline' || t.tt === 'dang_thuc_hien');
        const updLabel = isBGD() ? '✏ Cập nhật' : '✏ Báo cáo';
        const alreadySent = !isBGD() && canUpd && _pendingIds.has(t.id);
        const updBtn = canUpd
          ? (alreadySent
              ? `<button class="btn-upd btn-sent" data-id="${t.id}" data-ten="${t.ten.replace(/"/g,'&quot;')}" data-phong="${t.phong}" data-phoi="${t.phoi_hop||''}" onclick="openUpd(this.dataset.id,this.dataset.ten,this.dataset.phong,this.dataset.phoi)">↺ Cập nhật lại</button>`
              : `<button class="btn-upd" data-id="${t.id}" data-ten="${t.ten.replace(/"/g,'&quot;')}" data-phong="${t.phong}" data-phoi="${t.phoi_hop||''}" onclick="openUpd(this.dataset.id,this.dataset.ten,this.dataset.phong,this.dataset.phoi)">${updLabel}</button>`)
          : '';
        return `<tr>
          <td class="task-id">${t.id}</td>
          <td class="task-ten">${t.ten}${parseInt(t.nhac)>=2?`<span class="task-nhac">🔁${t.nhac}x</span>`:''}</td>
          <td><span style="font-size:11px;color:var(--muted)">${t.phoi_hop||'—'}</span></td>
          <td style="white-space:nowrap;font-size:12px">${fmtDate(t.bat_dau)}</td>
          <td style="white-space:nowrap;font-size:12px">${t.ket_thuc?fmtDate(t.ket_thuc):'—'}</td>
          <td class="nguon-cell" title="${t.nguon}">${nguonShort}</td>
          <td>${statusPill(t.tt)}${updBtn}</td>
        </tr>`;
      }).join('');

      parts.push(`
        <div class="dept-section">
          <div class="dept-section-header" onclick="toggleDept('${uid}')">
            <div class="dept-section-avatar" style="background:${color}">${dept.slice(0,4)}</div>
            <div class="dept-section-name">${dept}</div>
            <div class="dept-badges">
              ${done   ? `<span class="badge badge-green">${done} xong</span>`  : ''}
              ${active ? `<span class="badge badge-blue">${active} đang</span>` : ''}
              ${late   ? `<span class="badge badge-red">${late} trễ</span>`     : ''}
              <span class="badge badge-gray">${tasks.length} task</span>
            </div>
            <span class="toggle-ic" id="ic-${uid}">▼</span>
          </div>
          <div class="task-table-wrap" id="${uid}">
            <table class="task-table">
              <thead><tr>
                <th>ID</th><th>Đầu việc</th><th>Phối hợp</th>
                <th>Bắt đầu</th><th>Deadline</th><th>Biên Bản</th><th>Trạng thái</th>
              </tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>`);
    });
  });

  container.innerHTML = parts.join('');

  document.getElementById('tasks-count-label').textContent =
    `${filtered.length} đầu việc · ${totalDepts.size} phòng ban`;
}

function toggleDept(uid) {
  const el   = document.getElementById(uid);
  const icon = document.getElementById('ic-' + uid);
  el.classList.toggle('hidden');
  if (icon) icon.textContent = el.classList.contains('hidden') ? '▶' : '▼';
}

function filterTasks() {
  const nhom   = document.getElementById('filter-nhom').value;
  const status = document.getElementById('filter-status').value;
  const dept   = document.getElementById('filter-dept').value;
  const search = (document.getElementById('filter-search').value || '').toLowerCase().trim();

  const base = window._myTasks || D.tasks;
  const filtered = base.filter(t => {
    if (nhom && t.nhom !== nhom) return false;
    if (status === 'chua_xong') { if (t.tt === 'da_hoan_thanh') return false; }
    else if (status && t.tt !== status) return false;
    if (dept   && t.phong !== dept)   return false;
    if (search && !t.ten.toLowerCase().includes(search) && !t.phong.toLowerCase().includes(search)) return false;
    return true;
  });
  buildTasksView(filtered);
}

function initTasksView() {
  if (tasksRendered) return;
  tasksRendered = true;

  const myTasks = window._myTasks || D.tasks;
  const deptFilter = document.getElementById('filter-dept');
  [...new Set(myTasks.map(t => t.phong || 'Khác'))].sort().forEach(d => {
    const o = document.createElement('option');
    o.value = d; o.textContent = d;
    deptFilter.appendChild(o);
  });
  // Default: chỉ hiện trễ + đang làm
  document.getElementById('filter-status').value = 'chua_xong';
  filterTasks();
}

// ── Dashboard search ───────────────────────────────────────────────────────────
function handleDashSearch(val) {
  const q = val.toLowerCase().trim();
  const resEl  = document.getElementById('dash-search-results');
  const listEl = document.getElementById('dash-search-list');
  if (!q) { resEl.style.display = 'none'; return; }

  const found = (window._myTasks || D.tasks).filter(t =>
    t.ten.toLowerCase().includes(q) || t.phong.toLowerCase().includes(q)
  ).slice(0, 20);

  resEl.style.display = 'block';
  if (!found.length) {
    listEl.innerHTML = '<p style="color:var(--muted);padding:12px 0">Không tìm thấy.</p>';
    return;
  }

  let html = '<table class="search-result-table"><thead><tr><th>ID</th><th>Đầu việc</th><th>Phòng</th><th>Deadline</th><th>Biên Bản</th><th>Trạng thái</th></tr></thead><tbody>';
  found.forEach(t => {
    const nguonShort = t.nguon ? t.nguon.replace(/^Biên bản /, '') : '—';
    html += `<tr>
      <td class="task-id">${t.id}</td>
      <td style="max-width:300px">${t.ten}</td>
      <td style="font-size:12px">${t.phong}</td>
      <td style="font-size:12px;white-space:nowrap">${fmtDate(t.ket_thuc)}</td>
      <td class="nguon-cell">${nguonShort}</td>
      <td>${statusPill(t.tt)}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  listEl.innerHTML = html;
}

function clearDashSearch() {
  document.getElementById('dash-search').value = '';
  document.getElementById('dash-search-results').style.display = 'none';
}

// ── View routing ───────────────────────────────────────────────────────────────
function switchView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item[data-view]').forEach(n => n.classList.remove('active'));
  const v = document.getElementById('view-' + name);
  if (v) v.classList.add('active');
  const n = document.querySelector(`[data-view="${name}"]`);
  if (n) n.classList.add('active');
  if (name === 'tasks')  initTasksView();
  if (name === 'review') renderReview();
}

document.querySelectorAll('[data-view]').forEach(el => {
  el.addEventListener('click', () => switchView(el.dataset.view));
});

// ── Pending updates ────────────────────────────────────────────────────────────
const PK = 'bvtd_pending', AK = 'bvtd_approved';
const TT_LABELS = {da_hoan_thanh:'✅ Hoàn thành', dang_thuc_hien:'🔄 Đang làm', tre_deadline:'⚠️ Trễ Deadline'};
let _updTask = null;

function isBGD() { return AUTH && AUTH.user === 'BGD'; }
function lsGet(k) { try { return JSON.parse(localStorage.getItem(k)||'[]'); } catch(e) { return []; } }
function lsSave(k, v) { localStorage.setItem(k, JSON.stringify(v)); }

function fmtDateInput(el) {
  let v = el.value.replace(/[^\d]/g, '');
  if (v.length > 2) v = v.slice(0,2) + '/' + v.slice(2);
  if (v.length > 5) v = v.slice(0,5) + '/' + v.slice(5,9);
  el.value = v;
}

function openUpd(id, ten, phong, phoi) {
  _updTask = {id, ten, phong, phoi: phoi || ''};
  document.getElementById('upd-sub').textContent = id + ' — ' + ten + ' (' + phong + ')';
  document.getElementById('upd-tt').value = '';
  document.getElementById('upd-ngay').value = '';
  document.getElementById('upd-note').value = '';
  document.getElementById('upd-ngay-wrap').style.display = '';
  document.getElementById('upd-msg').style.display = 'none';
  document.getElementById('upd-modal').style.display = 'flex';
}
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('upd-tt').addEventListener('change', function() {
    const wrap = document.getElementById('upd-ngay-wrap');
    wrap.style.display = this.value === 'dang_thuc_hien' ? 'none' : '';
    if (this.value === 'dang_thuc_hien') document.getElementById('upd-ngay').value = '';
  });
});
function closeUpd() { document.getElementById('upd-modal').style.display = 'none'; }
function showUpdMsg(msg, isErr) {
  const el = document.getElementById('upd-msg');
  el.textContent = msg;
  el.className = isErr ? 'msg-err' : 'msg-ok';
  el.style.display = 'block';
}

function submitUpd() {
  if (!_updTask) return;
  const tt = document.getElementById('upd-tt').value;
  let ngayRaw = document.getElementById('upd-ngay').value.trim();
  const note = document.getElementById('upd-note').value.trim();
  if (!tt) { showUpdMsg('Vui lòng chọn trạng thái.', true); return; }
  if (tt === 'da_hoan_thanh' && !ngayRaw) { showUpdMsg('Vui lòng nhập ngày hoàn thành.', true); return; }
  let ngay = '';
  if (ngayRaw) {
    if (/^\d{2}\/\d{2}\/\d{4}$/.test(ngayRaw)) {
      const [d,m,y] = ngayRaw.split('/');
      ngay = y + '-' + m + '-' + d;
    } else {
      showUpdMsg('Ngày không hợp lệ. Vui lòng nhập đúng định dạng dd/mm/yyyy.', true); return;
    }
    // Kiểm tra ngày HT >= ngày nhắc cuối (task nhắc >= 2 lần)
    const _tr = (window._myTasks || D.tasks).find(t => t.id === _updTask.id);
    if (_tr && parseInt(_tr.nhac || '1') >= 2 && _tr.last_reminder && ngay < _tr.last_reminder) {
      showUpdMsg('❌ Ngày hoàn thành không hợp lệ! Nhiệm vụ này đã bị nhắc ' + _tr.nhac + ' lần — lần nhắc cuối: ' + fmtDate(_tr.last_reminder) + '. Ngày hoàn thành phải từ ' + fmtDate(_tr.last_reminder) + ' trở đi.', true);
      return;
    }
  }
  // Kiểm tra user báo cáo là phòng chính hay chỉ phối hợp (BGD depts=null → xem tất cả)
  const isPhongChinh = !AUTH.depts || AUTH.depts.some(d => d === _updTask.phong);
  const isPhongPhoi = !isPhongChinh && _updTask.phoi && AUTH.depts && AUTH.depts.some(d =>
    _updTask.phoi.split(', ').map(p => p.trim()).includes(d)
  );
  let finalNote = note || '';
  if (isPhongPhoi) {
    const flag = `⚠️ Báo cáo từ phòng phối hợp (${AUTH.user}) — cần kiểm tra lại với phòng chính (${_updTask.phong})`;
    finalNote = finalNote ? flag + ' | ' + finalNote : flag;
  }
  const userPhong = AUTH.depts ? AUTH.depts.join(', ') : AUTH.user;
  const entry = {id:_updTask.id, ten:_updTask.ten, phong:_updTask.phong,
                 trang_thai:tt, ngay_ht:ngay, ghi_chu:finalNote, user:AUTH.user,
                 user_phong:userPhong,
                 at:new Date().toISOString().slice(0,10)};
  if (isBGD()) {
    // BGĐ → thẳng vào approved queue, xuất JSON rồi chạy /check
    const appr = lsGet(AK);
    const idx = appr.findIndex(a => a.id === _updTask.id);
    if (idx >= 0) appr[idx] = entry; else appr.push(entry);
    lsSave(AK, appr);
    showUpdMsg('✓ Đã lưu. Nhấn "Xuất JSON" trong panel bên dưới để áp dụng vào database.', false);
    setTimeout(() => { closeUpd(); renderPending(); }, 1200);
  } else {
    // Phòng ban → pending queue, mỗi user/phòng giữ 1 entry riêng cho cùng task
    const arr = lsGet(PK);
    const idx = arr.findIndex(p => p.id === _updTask.id && p.user === AUTH.user);
    if (idx >= 0) arr[idx] = entry; else arr.push(entry);
    lsSave(PK, arr);
    // Cập nhật button ngay trên DOM → user thấy phản hồi tức thì
    const _btn = document.querySelector(`button.btn-upd[data-id="${_updTask.id}"]`);
    if (_btn) {
      _btn.textContent = '↺ Cập nhật lại';
      _btn.classList.add('btn-sent');
    }
    showUpdMsg('✓ Đã gửi báo cáo. BGĐ sẽ duyệt trong lần /check tiếp theo.', false);
    setTimeout(closeUpd, 1500);
  }
}

// ── Review view (BGĐ only) ────────────────────────────────────────────────────
function renderReview() {
  if (!isBGD()) return;
  const approved = lsGet(AK);
  const doneKeys = new Set(approved.map(a => a.id + '|' + a.user));
  const pending  = lsGet(PK).filter(p => !doneKeys.has(p.id + '|' + p.user));
  const depts    = new Set(pending.map(p => p.user));

  // KPI
  document.getElementById('rv-pending-count').textContent  = pending.length;
  document.getElementById('rv-approved-count').textContent = approved.length;
  document.getElementById('rv-depts-count').textContent    = depts.size;
  document.getElementById('rv-pending-badge').textContent  = pending.length;
  document.getElementById('rv-approved-badge').textContent = approved.length;
  document.getElementById('review-subtitle').textContent   =
    pending.length
      ? pending.length + ' cập nhật đang chờ từ ' + depts.size + ' phòng ban'
      : 'Không có cập nhật nào đang chờ duyệt';
  const topBtn = document.getElementById('review-export-top');
  if (topBtn) topBtn.style.display = approved.length ? '' : 'none';

  // Pending list
  const pendEl = document.getElementById('rv-pending-list');
  if (!pending.length) {
    pendEl.innerHTML = '<div class="rv-empty">🎉 Không có cập nhật nào đang chờ duyệt</div>';
  } else {
    const grouped = {};
    pending.forEach(p => { if (!grouped[p.id]) grouped[p.id] = []; grouped[p.id].push(p); });
    pendEl.innerHTML = Object.values(grouped).map(grp => {
      const first = grp[0];
      const task  = D.tasks.find(t => t.id === first.id);
      const curTT = task ? statusPill(task.tt) : '';
      const taskMeta = task ? [
        task.ket_thuc ? `⏰ Deadline: <b>${fmtDate(task.ket_thuc)}</b>` : `<span style="color:var(--muted)">Không có deadline</span>`,
        task.bat_dau  ? `📅 Giao: ${fmtDate(task.bat_dau)}` : '',
        task.phoi_hop ? `🤝 Phối hợp: ${task.phoi_hop}` : '',
        task.nguon    ? `📄 ${task.nguon}` : '',
      ].filter(Boolean).join(' &ensp;·&ensp; ') : '';
      const reporters = grp.map(p => `
        <div class="rv-reporter">
          <span class="rv-reporter-phong">${p.user_phong || p.user}</span>
          <div class="rv-reporter-body">
            <div style="font-size:13px;font-weight:600;">${TT_LABELS[p.trang_thai] || p.trang_thai || '—'}</div>
            ${p.ngay_ht ? `<div class="rv-item-meta">📅 Ngày hoàn thành: <b>${p.ngay_ht}</b></div>` : ''}
            ${p.ghi_chu ? `<div class="rv-item-meta">📝 ${p.ghi_chu}</div>` : ''}
            <div class="rv-item-meta" style="margin-top:4px;">Báo cáo ngày ${p.at}</div>
          </div>
          <div class="rv-reporter-actions">
            <button class="btn-appr" onclick="approveUpd('${p.id}','${p.user}')">✓ Duyệt</button>
            <button class="btn-rejt"  onclick="rejectUpd('${p.id}','${p.user}')">✕ Từ chối</button>
          </div>
        </div>`).join('');
      return `
        <div class="rv-item pending-color">
          <div class="rv-item-hdr">
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <span class="task-id">${first.id}</span>
                <span style="font-size:14px;font-weight:700;">${first.ten}</span>
              </div>
              <div class="rv-item-meta" style="margin-top:6px;">
                Phòng chính: <b>${first.phong}</b>&ensp;|&ensp;Trạng thái hiện tại: ${curTT}
              </div>
              ${taskMeta ? `<div class="rv-item-meta" style="margin-top:4px;">${taskMeta}</div>` : ''}
            </div>
            ${grp.length > 1 ? `<span class="badge badge-orange">${grp.length} phòng</span>` : ''}
          </div>
          ${reporters}
        </div>`;
    }).join('');
  }

  // Approved list
  const apprEl = document.getElementById('rv-approved-list');
  const expBtn = document.getElementById('rv-export-btn');
  if (!approved.length) {
    apprEl.innerHTML = '<div class="rv-empty" style="padding:20px 0;">Chưa có mục nào được duyệt.</div>';
    if (expBtn) expBtn.style.display = 'none';
  } else {
    apprEl.innerHTML = approved.map(a => `
      <div class="rv-item approved-color">
        <div class="rv-item-hdr">
          <div style="flex:1;min-width:0;">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <span class="task-id">${a.id}</span>
              <span style="font-size:14px;font-weight:700;">${a.ten}</span>
            </div>
            <div class="rv-item-meta" style="margin-top:4px;">
              Phòng: <b>${a.user_phong || a.user}</b> &ensp;·&ensp; Phòng chính: ${a.phong} &ensp;·&ensp; ngày ${a.at}
            </div>
            ${TT_LABELS[a.trang_thai] ? `<div class="rv-item-meta" style="margin-top:4px;">${TT_LABELS[a.trang_thai]}</div>` : ''}
            ${a.ngay_ht ? `<div class="rv-item-meta">📅 Ngày hoàn thành: <b>${a.ngay_ht}</b></div>` : ''}
            ${a.ghi_chu ? `<div class="rv-item-meta">📝 ${a.ghi_chu}</div>` : ''}
          </div>
          <button class="btn-rejt" style="flex-shrink:0;align-self:flex-start;" onclick="removeApproved('${a.id}')">✕ Bỏ</button>
        </div>
      </div>`).join('');
    if (expBtn) expBtn.style.display = '';
  }

  updateNavBadge();
}

function updateNavBadge() {
  const navEl = document.getElementById('nav-review');
  const badge = document.getElementById('nav-review-badge');
  if (!isBGD()) { if (navEl) navEl.style.display = 'none'; return; }
  if (navEl) navEl.style.display = 'flex';
  const approved  = lsGet(AK);
  const doneKeys  = new Set(approved.map(a => a.id + '|' + a.user));
  const count     = lsGet(PK).filter(p => !doneKeys.has(p.id + '|' + p.user)).length;
  if (badge) {
    badge.textContent   = count;
    badge.style.display = count > 0 ? 'inline-flex' : 'none';
  }
}

function renderPending() {
  const panel = document.getElementById('pending-panel');
  if (!panel || !isBGD()) { if (panel) panel.innerHTML = ''; return; }
  const approvedItems = lsGet(AK);
  const doneIds = new Set(approvedItems.map(a => a.id));
  const pendingItems = lsGet(PK).filter(p => !doneIds.has(p.id));
  if (!pendingItems.length && !approvedItems.length) { panel.innerHTML = ''; return; }

  let h = '<div class="pending-panel">';

  if (pendingItems.length) {
    h += `<div class="pending-hdr" style="margin-bottom:8px;">⏳ Chờ duyệt — ${pendingItems.length} cập nhật từ phòng ban</div>`;
    // Group theo task ID
    const grouped = {};
    pendingItems.forEach(p => { if (!grouped[p.id]) grouped[p.id] = []; grouped[p.id].push(p); });
    Object.values(grouped).forEach(grp => {
      const first = grp[0];
      const multiPhong = grp.length > 1;
      h += `<div class="pending-item" style="${multiPhong?'border-left:3px solid #f6ad55;':''}">
        <div class="pending-info" style="width:100%;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <span class="task-id">${first.id}</span>
            <div class="pending-name" style="margin:0;">${first.ten}</div>
            <span style="font-size:11px;color:#718096;margin-left:auto;">Phòng chính: <b>${first.phong}</b></span>
          </div>
          ${grp.map((p,i) => `
          <div style="border:1px solid #e2e8f0;border-radius:6px;padding:8px 10px;margin-bottom:${i<grp.length-1?'6px':'0'};background:${i%2===0?'#f7fafc':'#fff'};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <span style="font-size:12px;font-weight:700;color:#2d3748;">📤 ${p.user_phong||p.user}</span>
              <span style="font-size:11px;color:#a0aec0;">ngày ${p.at}</span>
            </div>
            ${p.trang_thai?`<div class="pending-meta" style="margin-top:4px;">${TT_LABELS[p.trang_thai]||p.trang_thai}</div>`:''}
            ${p.ngay_ht?`<div class="pending-meta" style="margin-top:2px;">📅 Ngày HT: ${p.ngay_ht}</div>`:''}
            ${p.ghi_chu?`<div class="pending-meta" style="margin-top:2px;">📝 ${p.ghi_chu}</div>`:''}
            <div style="display:flex;gap:6px;margin-top:6px;">
              <button class="btn-appr" onclick="approveUpd('${p.id}','${p.user}')">✓ Duyệt</button>
              <button class="btn-rejt" onclick="rejectUpd('${p.id}','${p.user}')">✕ Từ chối</button>
            </div>
          </div>`).join('')}
        </div>
      </div>`;
    });
  }

  if (approvedItems.length) {
    if (pendingItems.length) h += '<div style="height:1px;background:var(--border);margin:12px 0;"></div>';
    h += `<div style="font-size:13px;font-weight:700;color:#276749;margin-bottom:8px;">✅ Đã duyệt / BGĐ cập nhật trực tiếp — ${approvedItems.length} mục</div>`;
    approvedItems.forEach(a => {
      h += `<div class="pending-item" style="border-color:#c6f6d5;">
        <div class="pending-info">
          <span class="task-id">${a.id}</span>
          <div class="pending-name">${a.ten}</div>
          <div class="pending-meta">${a.phong} · ${a.user} ngày ${a.at}</div>
          ${a.trang_thai?`<div class="pending-meta">${TT_LABELS[a.trang_thai]||a.trang_thai}</div>`:''}
          ${a.ngay_ht?`<div class="pending-meta">📅 Ngày HT: ${a.ngay_ht}</div>`:''}
          ${a.ghi_chu?`<div class="pending-meta">📝 ${a.ghi_chu}</div>`:''}
        </div>
        <button class="btn-rejt" style="flex-shrink:0;margin-top:4px;" onclick="removeApproved('${a.id}')">✕</button>
      </div>`;
    });
  }

  h += `<div style="margin-top:14px;display:flex;justify-content:flex-end;">
    <button class="btn-exp" onclick="exportApproved()">⬇ Xuất JSON để chạy /check (${approvedItems.length} mục)</button>
  </div>`;

  panel.innerHTML = h + '</div>';
}

// ── GitHub Auto-Upload (BGĐ) ──────────────────────────────────────────────────
const GH_TOKEN_KEY = 'bvtd_gh_token';
const GH_REPO      = 'dragonhuynh/bvtd-progress';
const GH_PATH      = 'data/pending_updates.json';

function showGHTokenSetup() {
  const cur = localStorage.getItem(GH_TOKEN_KEY) || '';
  const tok = prompt(
    'Nhập GitHub Personal Access Token

' +
    'Cách tạo token:
' +
    '1. Vào github.com → Settings → Developer settings
' +
    '2. Personal access tokens → Fine-grained tokens → Generate new
' +
    '3. Repository: dragonhuynh/bvtd-progress
' +
    '4. Permissions: Contents → Read and write

' +
    'Token hiện tại: ' + (cur ? cur.slice(0,8)+'...' : '(chưa có)'),
    cur
  );
  if (tok !== null) {
    localStorage.setItem(GH_TOKEN_KEY, tok.trim());
    alert(tok.trim() ? '✓ Đã lưu token.' : '✓ Đã xóa token.');
  }
}

async function uploadToGitHub() {
  const approved = lsGet(AK);
  if (!approved.length) { alert('Chưa có cập nhật nào được duyệt.'); return; }

  let token = localStorage.getItem(GH_TOKEN_KEY) || '';
  if (!token) {
    token = prompt('Nhập GitHub Personal Access Token
(Chỉ cần nhập 1 lần — lưu vào bộ nhớ):') || '';
    if (!token) return;
    localStorage.setItem(GH_TOKEN_KEY, token.trim());
    token = token.trim();
  }

  const btn = document.getElementById('btn-gh-upload');
  if (btn) { btn.textContent = '⏳ Đang gửi...'; btn.disabled = true; }

  const apiUrl = `https://api.github.com/repos/${GH_REPO}/contents/${GH_PATH}`;
  const headers = {
    'Authorization': `Bearer ${token}`,
    'Accept': 'application/vnd.github.v3+json',
    'Content-Type': 'application/json',
  };

  try {
    // Lấy SHA nếu file đã tồn tại (cần cho PUT)
    let sha = '';
    const chk = await fetch(apiUrl, { headers });
    if (chk.ok) sha = (await chk.json()).sha || '';

    // Upload
    const payload = JSON.stringify(approved, null, 2);
    const content  = btoa(unescape(encodeURIComponent(payload)));
    const body = {
      message: `dashboard: ${approved.length} cập nhật BGĐ duyệt ngày ${new Date().toLocaleDateString('vi-VN')}`,
      content,
      ...(sha ? { sha } : {}),
    };

    const resp = await fetch(apiUrl, { method: 'PUT', headers, body: JSON.stringify(body) });

    if (resp.ok) {
      lsSave(AK, []);
      renderReview();
      updateNavBadge();
      if (btn) { btn.textContent = '✓ Đã gửi!'; btn.disabled = false; }
      alert(
        '✓ Đã gửi lên GitHub thành công!\n\n' +
        'GitHub Actions sẽ tự động:\n' +
        '  1. Cập nhật tasks.csv\n' +
        '  2. Sinh lại dashboard HTML\n' +
        '  3. Deploy lên trang web\n\n' +
        'Tải lại trang sau ~1–2 phút để thấy kết quả.'
      );
    } else {
      const err = await resp.json().catch(() => ({}));
      if (btn) { btn.textContent = '📤 Gửi lên GitHub — tự động cập nhật'; btn.disabled = false; }
      if (resp.status === 401) {
        localStorage.removeItem(GH_TOKEN_KEY);
        alert('❌ Token không hợp lệ hoặc hết hạn. Nhấn ⚙ để nhập lại.');
      } else if (resp.status === 403) {
        alert('❌ Token thiếu quyền. Cần quyền "Contents: Read and write" cho repo bvtd-progress.');
      } else {
        alert(`❌ Lỗi ${resp.status}: ${err.message || 'Không rõ nguyên nhân'}`);
      }
    }
  } catch(e) {
    if (btn) { btn.textContent = '📤 Gửi lên GitHub — tự động cập nhật'; btn.disabled = false; }
    alert('❌ Lỗi kết nối: ' + e.message + '\nKiểm tra kết nối internet.');
  }
}

function removeApproved(id) {
  lsSave(AK, lsGet(AK).filter(a => a.id !== id));
  renderPending(); renderReview();
}

function approveUpd(id, user) {
  const all = lsGet(PK);
  const item = all.find(p => p.id === id && p.user === user);
  if (!item) return;
  lsSave(PK, all.filter(p => !(p.id === id && p.user === user)));
  const appr = lsGet(AK);
  const idx = appr.findIndex(a => a.id === id);
  if (idx >= 0) appr[idx] = item; else appr.push(item);
  lsSave(AK, appr);
  renderPending(); renderReview();
}

function rejectUpd(id, user) {
  lsSave(PK, lsGet(PK).filter(p => !(p.id === id && p.user === user)));
  renderPending(); renderReview();
}

function exportApproved() {
  const appr = lsGet(AK);
  if (!appr.length) { alert('Chưa có cập nhật nào được duyệt.'); return; }
  const blob = new Blob([JSON.stringify(appr, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'pending_updates.json';
  a.click();
  lsSave(AK, []);
  renderPending(); renderReview();
  alert('✓ Đã tải file cập nhật về máy.\nĐặt file pending_updates.json vào thư mục data/ rồi chạy /check để áp dụng.');
}

// ── Boot ───────────────────────────────────────────────────────────────────────
const savedAuth = sessionStorage.getItem('bvtd_auth') || localStorage.getItem('bvtd_auth');
if (savedAuth) {
  let _sa = null;
  try { _sa = JSON.parse(savedAuth); }
  catch(e) { localStorage.removeItem('bvtd_auth'); sessionStorage.removeItem('bvtd_auth'); }
  if (_sa && _sa.user && _sa.user in USERS) {
    AUTH = _sa;
    document.getElementById('login-overlay').style.display = 'none';
    document.getElementById('app-body').style.display = 'flex';
    document.getElementById('user-badge').textContent = AUTH.user;
    initApp();
  }
}
</script>
