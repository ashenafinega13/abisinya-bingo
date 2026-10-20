<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin Panel</title>
<style>
  :root { --bg:#0b0616; --card:#131b2e; --ink:#f5f3ff; --muted:#a78bfa; --accent:#8b5cf6; --border:#2a1b54; --green:#22c55e; --red:#ef4444; }
  * { box-sizing:border-box; margin:0; padding:0; font-family:'Segoe UI',sans-serif; }
  body { background:var(--bg); color:var(--ink); padding:20px; }
  .container { max-width:1000px; margin:0 auto; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:20px; }
  h1 { color:var(--muted); margin-bottom:20px; }
  h2 { font-size:18px; margin-bottom:15px; color:#fff; }
  .tabs { display:flex; gap:10px; margin-bottom:20px; border-bottom:1px solid var(--border); padding-bottom:10px; overflow-x:auto; }
  .tab { background:none; border:none; color:var(--muted); font-weight:bold; font-size:14px; cursor:pointer; padding:10px 15px; border-radius:6px; }
  .tab.active { background:var(--accent); color:#fff; }
  .stats { display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:15px; }
  .stat { background:rgba(255,255,255,0.05); padding:15px; border-radius:8px; text-align:center; }
  .stat b { display:block; font-size:24px; color:#fff; margin-top:5px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { padding:12px; text-align:left; border-bottom:1px solid var(--border); }
  th { color:var(--muted); }
  input, button { padding:10px; border-radius:6px; border:1px solid var(--border); background:#0d1625; color:#fff; outline:none; }
  button { background:var(--accent); color:#fff; border:none; cursor:pointer; font-weight:bold; }
  button:hover { opacity:0.9; }
  .btn-green { background:var(--green); } .btn-red { background:var(--red); }
  .hidden { display:none !important; }
  .login { max-width:300px; margin:100px auto; text-align:center; }
  .tag { padding:4px 8px; border-radius:4px; font-size:11px; font-weight:bold; }
  .tag-pending { background:#f59e0b; color:#000; }
  .tag-approved { background:var(--green); color:#000; }
</style>
</head>
<body>

<div id="loginScreen" class="login">
  <div class="card">
    <h2>Admin Login</h2>
    <input id="pwd" type="password" placeholder="Password" style="width:100%; margin-bottom:10px;">
    <button onclick="login()" style="width:100%;">Login</button>
  </div>
</div>

<div id="dashboard" class="container hidden">
  <h1>👑 Admin Dashboard</h1>
  
  <div class="tabs">
    <button class="tab active" onclick="switchTab('overview')">Overview</button>
    <button class="tab" onclick="switchTab('withdrawals')">Withdrawals</button>
    <button class="tab" onclick="switchTab('deposits')">Deposits</button>
    <button class="tab" onclick="switchTab('users')">Users</button>
    <button class="tab" onclick="switchTab('settings')">Settings</button>
    <button class="tab" onclick="logout()" style="margin-left:auto; color:#ef4444">Logout</button>
  </div>

  <!-- OVERVIEW -->
  <div id="tab-overview" class="tab-content">
    <div class="stats" id="overviewStats"></div>
  </div>

  <!-- WITHDRAWALS -->
  <div id="tab-withdrawals" class="tab-content hidden">
    <div class="card">
      <table><thead><tr><th>User ID</th><th>Amount</th><th>Phone</th><th>Status</th><th>Date</th><th>Action</th></tr></thead><tbody id="withdrawTable"></tbody></table>
    </div>
  </div>

  <!-- DEPOSITS -->
  <div id="tab-deposits" class="tab-content hidden">
    <div class="card">
      <table><thead><tr><th>User ID</th><th>Amount</th><th>SMS</th><th>Status</th><th>Date</th><th>Action</th></tr></thead><tbody id="depositTable"></tbody></table>
    </div>
  </div>

  <!-- USERS (Search & View) -->
  <div id="tab-users" class="tab-content hidden">
    <div class="card">
      <h2>Search User by Telegram ID</h2>
      <div style="display:flex; gap:10px; margin-bottom:20px;">
        <input id="searchUid" placeholder="e.g. 715580610" style="flex:1;">
        <button onclick="searchUser()">Search</button>
      </div>
      <div id="userResult" class="hidden">
        <div class="stats" id="userStats"></div>
        <h2 style="margin-top:20px;">Recent History</h2>
        <table><thead><tr><th>Type</th><th>Amount</th><th>Date</th></tr></thead><tbody id="userHistory"></tbody></table>
      </div>
    </div>
  </div>

  <!-- SETTINGS -->
  <div id="tab-settings" class="tab-content hidden">
    <div class="card">
      <h2>Game Settings</h2>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px;">
        <div><label>Entry Fee (ETB)</label><input id="setFee" type="number" style="width:100%; margin-top:5px;"></div>
        <div><label>Prize % (e.g. 80)</label><input id="setPct" type="number" style="width:100%; margin-top:5px;"></div>
        <div><label>Selection Time (Sec)</label><input id="setTime" type="number" style="width:100%; margin-top:5px;"></div>
      </div>
      <button onclick="saveSettings()" style="margin-top:15px;">Save Settings</button>
    </div>
    <div class="card">
      <h2>Danger Zone</h2>
      <p style="color:var(--muted); margin-bottom:10px;">Permanently delete transaction history.</p>
      <button class="btn-red" onclick="clearHistory('deposits')">Clear Deposits</button>
      <button class="btn-red" onclick="clearHistory('withdrawals')">Clear Withdrawals</button>
      <button class="btn-red" onclick="clearHistory('all')">Clear ALL History</button>
    </div>
  </div>
</div>

<script>
let pwd = localStorage.getItem('admin_pwd');

async function login() {
  pwd = document.getElementById('pwd').value;
  const res = await fetch('/api/admin/stats', { headers: { 'x-admin-pass': pwd } });
  if (res.ok) { localStorage.setItem('admin_pwd', pwd); showDashboard(); } 
  else alert('Wrong password');
}
function logout() { localStorage.removeItem('admin_pwd'); location.reload(); }

function showDashboard() {
  document.getElementById('loginScreen').classList.add('hidden');
  document.getElementById('dashboard').classList.remove('hidden');
  loadOverview(); loadDeposits(); loadWithdrawals(); loadSettings();
}

function switchTab(t) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + t).classList.remove('hidden');
  event.target.classList.add('active');
}

async function loadOverview() {
  const res = await fetch('/api/admin/stats', { headers: { 'x-admin-pass': pwd } });
  const d = await res.json();
  document.getElementById('overviewStats').innerHTML = `
    <div class="stat"><small>Total Users</small><b>${d.users}</b></div>
    <div class="stat"><small>Active Players</small><b>${d.players}</b></div>
    <div class="stat"><small>Current Round</small><b>#${d.round}</b></div>
    <div class="stat"><small>Total Deposits</small><b style="color:var(--green)">${d.revenue.toFixed(0)} ETB</b></div>
    <div class="stat"><small>Total Withdrawals</small><b style="color:var(--red)">${d.payouts.toFixed(0)} ETB</b></div>
    <div class="stat"><small>Total Game Wins</small><b style="color:var(--muted)">${d.winsPaid.toFixed(0)} ETB</b></div>
    <div class="stat"><small>Current Jackpot</small><b style="color:#facc15">${d.jackpot} ETB</b></div>
  `;
}

async function loadWithdrawals() {
  const res = await fetch('/api/admin/withdrawals', { headers: { 'x-admin-pass': pwd } });
  const d = await res.json();
  document.getElementById('withdrawTable').innerHTML = d.txs.map(t => `
    <tr>
      <td>${t.userId}</td><td>${t.amount} ETB</td><td>${t.phone || '-'}</td>
      <td><span class="tag tag-${t.status}">${t.status}</span></td>
      <td>${new Date(t.createdAt).toLocaleString()}</td>
      <td>${t.status === 'pending' ? `<button class="btn-green" onclick="approve('${t._id}', true)">Approve</button> <button class="btn-red" onclick="approve('${t._id}', false)">Reject</button>` : '-'}</td>
    </tr>
  `).join('');
}

async function loadDeposits() {
  const res = await fetch('/api/admin/deposits', { headers: { 'x-admin-pass': pwd } });
  const d = await res.json();
  document.getElementById('depositTable').innerHTML = d.txs.map(t => `
    <tr>
      <td>${t.userId}</td><td>${t.amount} ETB</td><td>${t.sms || '-'}</td>
      <td><span class="tag tag-${t.status}">${t.status}</span></td>
      <td>${new Date(t.createdAt).toLocaleString()}</td>
      <td>${t.status === 'pending' ? `<button class="btn-green" onclick="approve('${t._id}', true)">Approve</button> <button class="btn-red" onclick="approve('${t._id}', false)">Reject</button>` : '-'}</td>
    </tr>
  `).join('');
}

async function approve(id, isApprove) {
  await fetch('/api/admin/transaction/' + id, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'x-admin-pass': pwd },
    body: JSON.stringify({ action: isApprove ? 'approve' : 'reject' })
  });
  loadDeposits(); loadWithdrawals(); loadOverview();
}

async function searchUser() {
  const uid = document.getElementById('searchUid').value;
  const res = await fetch('/api/admin/user/' + uid, { headers: { 'x-admin-pass': pwd } });
  const d = await res.json();
  if (d.error) return alert(d.error);
  
  document.getElementById('userResult').classList.remove('hidden');
  document.getElementById('userStats').innerHTML = `
    <div class="stat"><small>Name</small><b>${d.user.firstName}</b></div>
    <div class="stat"><small>Balance</small><b>${d.user.balance.toFixed(2)} ETB</b></div>
    <div class="stat"><small>Winnings</small><b>${d.user.winBalance.toFixed(2)} ETB</b></div>
  `;
  document.getElementById('userHistory').innerHTML = d.txs.map(t => `
    <tr><td>${t.type}</td><td>${t.amount} ETB</td><td>${new Date(t.createdAt).toLocaleString()}</td></tr>
  `).join('');
}

async function loadSettings() {
  const res = await fetch('/api/admin/settings', { headers: { 'x-admin-pass': pwd } });
  const d = await res.json();
  document.getElementById('setFee').value = d.settings.entryFee;
  document.getElementById('setPct').value = d.settings.prizePct;
  document.getElementById('setTime').value = d.settings.selectionSeconds;
}

async function saveSettings() {
  await fetch('/api/admin/settings', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'x-admin-pass': pwd },
    body: JSON.stringify({
      entryFee: Number(document.getElementById('setFee').value),
      prizePct: Number(document.getElementById('setPct').value),
      selectionSeconds: Number(document.getElementById('setTime').value)
    })
  });
  alert('Settings saved!');
}

async function clearHistory(type) {
  if (!confirm('Are you sure you want to delete history? This cannot be undone.')) return;
  await fetch('/api/admin/clear-history', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'x-admin-pass': pwd },
    body: JSON.stringify({ type })
  });
  alert('History cleared'); loadDeposits(); loadWithdrawals(); loadOverview();
}

if (pwd) showDashboard();
</script>
</body>
</html>