(function () {
  const form = document.getElementById("login-form");
  const err = document.getElementById("login-error");
  const btn = document.getElementById("login-btn");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.textContent = "";
    btn.disabled = true;
    btn.textContent = "Signing in…";
    try {
      const r = await fetch("api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Prax-Console": "1" },
        body: JSON.stringify({
          username: document.getElementById("username").value,
          password: document.getElementById("password").value,
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.error || "Sign-in failed");
      window.location.href = "./";
    } catch (ex) {
      err.textContent = ex.message;
      btn.disabled = false;
      btn.textContent = "Sign in";
    }
  });
})();
