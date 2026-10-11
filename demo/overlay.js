// Injected into every page while recording: title cards, captions and a visible pointer.
// State is kept in window.name, which survives navigation, so a card stays up across page loads.
(() => {
  if (window.top !== window) return;
  const fresh = { demo: true, card: __FIRST_CARD__, caption: "", x: 640, y: 360 };
  let state;
  try { state = JSON.parse(window.name); } catch (error) { state = null; }
  if (!state || !state.demo) state = fresh;

  // Keep the admin's navigation sidebar closed, so wide tables fit in the frame.
  try { localStorage.setItem("django.admin.navSidebarIsOpen", "false"); } catch (error) { /* no storage */ }

  const root = document.createElement("div");
  root.id = "demo-overlay";
  root.innerHTML = `
    <style>
      #demo-overlay, #demo-overlay * { box-sizing: border-box; font-family: Inter, "Liberation Sans", Arial, sans-serif; }
      #demo-overlay .card { position: fixed; inset: 0; z-index: 2147483646; display: flex; align-items: center;
        justify-content: center; text-align: center; background: #0b1f33; color: #fff; opacity: 0; pointer-events: none; }
      #demo-overlay .card.on { opacity: 1; }
      #demo-overlay .card h1 { font-size: 46px; font-weight: 700; margin: 0 0 18px; letter-spacing: -0.5px; }
      #demo-overlay .card p { font-size: 24px; margin: 0; color: #b8c7d9; }
      #demo-overlay .card .bar { width: 72px; height: 6px; background: #ffc107; margin: 0 auto 28px; border-radius: 3px; }
      #demo-overlay .caption { position: fixed; left: 50%; bottom: 26px; transform: translateX(-50%); z-index: 2147483645;
        max-width: 1040px; padding: 13px 26px; border-radius: 10px; background: rgba(11, 31, 51, 0.94); color: #fff;
        font-size: 22px; line-height: 1.35; text-align: center; opacity: 0; pointer-events: none;
        box-shadow: 0 6px 24px rgba(0, 0, 0, 0.3); }
      #demo-overlay .caption.on { opacity: 1; }
      #demo-overlay .pointer { position: fixed; left: -11px; top: -11px; width: 22px; height: 22px; border-radius: 50%;
        z-index: 2147483644; background: rgba(255, 193, 7, 0.75); border: 2px solid #fff; pointer-events: none;
        box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.35); }
      #demo-overlay .pointer.down { background: rgba(255, 120, 0, 0.95); width: 30px; height: 30px; left: -15px; top: -15px; }
      #demo-overlay.ready .card, #demo-overlay.ready .caption { transition: opacity 0.45s ease; }
    </style>
    <div class="card"><div><div class="bar"></div><h1></h1><p></p></div></div>
    <div class="caption"></div>
    <div class="pointer"></div>`;
  const card = root.querySelector(".card");
  const caption = root.querySelector(".caption");
  const pointer = root.querySelector(".pointer");

  const render = () => {
    window.name = JSON.stringify(state);
    card.classList.toggle("on", Boolean(state.card));
    if (state.card) {
      card.querySelector("h1").textContent = state.card.title;
      card.querySelector("p").textContent = state.card.subtitle || "";
    }
    caption.classList.toggle("on", Boolean(state.caption));
    if (state.caption) caption.textContent = state.caption;
    pointer.style.transform = `translate(${state.x}px, ${state.y}px)`;
  };

  const attach = () => {
    if (document.documentElement && !root.isConnected) document.documentElement.appendChild(root);
  };
  attach();
  new MutationObserver(attach).observe(document, { childList: true, subtree: true });

  document.addEventListener("mousemove", (event) => {
    // The browser reports a move to the corner on each page load; that is not the demo's pointer.
    if (event.clientX === 0 && event.clientY === 0) return;
    state.x = event.clientX;
    state.y = event.clientY;
    pointer.style.transform = `translate(${state.x}px, ${state.y}px)`;
  }, true);
  document.addEventListener("mousedown", () => pointer.classList.add("down"), true);
  document.addEventListener("mouseup", () => setTimeout(() => pointer.classList.remove("down"), 180), true);
  window.addEventListener("pagehide", () => { window.name = JSON.stringify(state); });

  window.__demo = { set(update) { Object.assign(state, update); render(); } };
  render();
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add("ready")));
})();
