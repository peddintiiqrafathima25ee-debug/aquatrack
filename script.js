const BASE = "http://127.0.0.1:5000";

// ── Sign In ──────────────────────────────────────────────────────────────────
function openSignIn()  { document.getElementById("signInModal").style.display = "flex"; }
function closeSignIn() { document.getElementById("signInModal").style.display = "none"; }

function submitSignIn() {
  const username = document.getElementById("siUsername").value.trim();
  const phone    = document.getElementById("siPhone").value.trim();
  const msg      = document.getElementById("siMsg");

  if (!username || !phone) { msg.style.color="red"; msg.innerText="Please fill all fields!"; return; }

  fetch(BASE + "/register", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ username, phone })
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      msg.style.color = "#52b788";
      msg.innerText = "Registered! Check your phone for confirmation SMS.";
      localStorage.setItem("aqUsername", username);
      localStorage.setItem("aqPhone", phone);
      setTimeout(closeSignIn, 2500);
    } else {
      msg.style.color = "red"; msg.innerText = data.error || "Registration failed.";
    }
  })
  .catch(() => { msg.style.color="red"; msg.innerText="Cannot connect to backend."; });
}

// ── Contact Form ─────────────────────────────────────────────────────────────
function sendMessage() {
  const name    = document.getElementById("name").value.trim();
  const phone   = document.getElementById("phone").value.trim();
  const message = document.getElementById("message").value.trim();

  if (!name || !phone || !message) { alert("Please fill all fields!"); return; }

  fetch(BASE + "/contact-sms", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ name, phone, message })
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      alert("Message sent! You will receive a confirmation SMS shortly.");
      document.getElementById("name").value = "";
      document.getElementById("phone").value = "";
      document.getElementById("message").value = "";
    } else {
      alert("Failed to send: " + (data.error || "Unknown error"));
    }
  })
  .catch(() => alert("Cannot connect to backend."));
}
// On page load — show My Account or Sign In based on login state
window.addEventListener('load', () => {
  const username = localStorage.getItem("aqUsername");
  const btn = document.querySelector('.hero button');  // Sign In button
  if (username && btn) {
    btn.innerText = `Hi, ${username}`;
    btn.onclick = () => window.location.href = 'account.html';
  }
});