(() => {
  const year = document.getElementById("year");
  if (year) year.textContent = String(new Date().getFullYear());

  const header = document.querySelector(".site-header");
  const onScroll = () => {
    if (!header) return;
    header.classList.toggle("is-scrolled", window.scrollY > 12);
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  const toggle = document.querySelector(".nav-toggle");
  const mobileNav = document.getElementById("mobile-nav");
  if (toggle && mobileNav) {
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!open));
      mobileNav.hidden = open;
      mobileNav.classList.toggle("is-open", !open);
    });
    mobileNav.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        toggle.setAttribute("aria-expanded", "false");
        mobileNav.hidden = true;
        mobileNav.classList.remove("is-open");
      });
    });
  }

  const animated = document.querySelectorAll("[data-animate]");
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-inview");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.16, rootMargin: "0px 0px -8% 0px" }
    );
    animated.forEach((el) => io.observe(el));
  } else {
    animated.forEach((el) => el.classList.add("is-inview"));
  }

  const form = document.getElementById("audit-form");
  const status = document.getElementById("form-status");
  if (!form || !status) return;

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    status.classList.remove("is-error");

    const data = new FormData(form);
    const name = String(data.get("name") || "").trim();
    const email = String(data.get("email") || "").trim();
    const pharmacy = String(data.get("pharmacy") || "").trim();
    const lgo = String(data.get("lgo") || "").trim();
    const message = String(data.get("message") || "").trim();

    if (!name || !email || !pharmacy || !lgo || !message) {
      status.textContent = "Merci de remplir tous les champs.";
      status.classList.add("is-error");
      return;
    }

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      status.textContent = "Adresse e-mail invalide.";
      status.classList.add("is-error");
      return;
    }

    const subject = encodeURIComponent(`Audit Clareo Officine — ${pharmacy}`);
    const body = encodeURIComponent(
      [
        `Nom : ${name}`,
        `E-mail : ${email}`,
        `Officine : ${pharmacy}`,
        `LGO : ${lgo}`,
        "",
        "Priorité :",
        message,
      ].join("\n")
    );

    status.textContent = "Ouverture de votre client mail…";
    window.location.href = `mailto:alexandre@clareo-solutions.fr?subject=${subject}&body=${body}`;
    form.reset();
  });
})();
