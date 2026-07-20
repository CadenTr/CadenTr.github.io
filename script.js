document.documentElement.classList.add("js");

(() => {
  "use strict";

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
  const header = document.querySelector("[data-site-header]");
  const navToggle = document.querySelector(".nav-toggle");
  const nav = document.querySelector("#primary-nav");
  const menuLinks = [...document.querySelectorAll(".primary-nav a")];
  const sectionLinks = menuLinks.filter((link) => link.getAttribute("href")?.startsWith("#"));
  const pageMain = document.querySelector("main");
  const siteFooter = document.querySelector("footer");

  const setHeaderState = () => {
    header?.classList.toggle("is-scrolled", window.scrollY > 24);
  };

  setHeaderState();
  window.addEventListener("scroll", setHeaderState, { passive: true });

  const setNavOpen = (open, returnFocus = false) => {
    if (!header || !navToggle) return;

    header.classList.toggle("nav-open", open);
    navToggle.setAttribute("aria-expanded", String(open));
    navToggle.querySelector(".sr-only").textContent = open ? "Close navigation" : "Open navigation";
    document.body.style.overflow = open ? "hidden" : "";
    [pageMain, siteFooter].forEach((region) => region?.toggleAttribute("inert", open));

    if (open) {
      window.requestAnimationFrame(() => menuLinks[0]?.focus());
    } else if (returnFocus) {
      navToggle.focus({ preventScroll: true });
    }
  };

  navToggle?.addEventListener("click", () => {
    const open = navToggle.getAttribute("aria-expanded") !== "true";
    setNavOpen(open);
  });

  menuLinks.forEach((link) => {
    link.addEventListener("click", () => {
      const wasOpen = header?.classList.contains("nav-open") ?? false;
      const href = link.getAttribute("href") ?? "";
      const target = href.startsWith("#") ? document.querySelector(href) : null;
      const targetHeading = target?.querySelector("h1, h2");

      setNavOpen(false, wasOpen);

      if (wasOpen && targetHeading) {
        const focusDelay = reducedMotion.matches ? 0 : 650;
        window.setTimeout(() => {
          targetHeading.setAttribute("tabindex", "-1");
          targetHeading.focus({ preventScroll: true });
        }, focusDelay);
      }
    });
  });

  document.addEventListener("keydown", (event) => {
    const navIsOpen = header?.classList.contains("nav-open") ?? false;

    if (event.key === "Escape" && navIsOpen) {
      setNavOpen(false, true);
      return;
    }

    if (event.key === "Tab" && navIsOpen && navToggle) {
      const focusable = [navToggle, ...menuLinks];
      const first = focusable[0];
      const last = focusable.at(-1);

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 900) setNavOpen(false);
  });

  const hero = document.querySelector("[data-hero]");
  const topicLinks = [...document.querySelectorAll("[data-topic-link]")];
  const topics = ["surveying", "engineering", "music"];
  const rotationDelay = 4200;
  let activeTopic = topics.includes(hero?.dataset.topic) ? hero.dataset.topic : topics[0];
  let rotationTimer = 0;
  let userSelectedTopic = false;
  let heroIsVisible = true;

  const setHeroTopic = (topic) => {
    if (!hero || !topics.includes(topic)) return;
    activeTopic = topic;
    hero.dataset.topic = topic;
  };

  const stopHeroRotation = () => {
    window.clearTimeout(rotationTimer);
    rotationTimer = 0;
  };

  const scheduleHeroRotation = () => {
    stopHeroRotation();
    if (!hero || userSelectedTopic || reducedMotion.matches || document.hidden || !heroIsVisible) return;

    rotationTimer = window.setTimeout(() => {
      const nextIndex = (topics.indexOf(activeTopic) + 1) % topics.length;
      setHeroTopic(topics[nextIndex]);
      scheduleHeroRotation();
    }, rotationDelay);
  };

  const selectHeroTopic = (topic) => {
    userSelectedTopic = true;
    stopHeroRotation();
    setHeroTopic(topic);
  };

  topicLinks.forEach((link) => {
    const topic = link.dataset.topicLink;

    link.addEventListener("pointerenter", () => {
      if (finePointer.matches) selectHeroTopic(topic);
    });

    link.addEventListener("focus", () => selectHeroTopic(topic));
    link.addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "mouse") selectHeroTopic(topic);
    });
    link.addEventListener("click", () => selectHeroTopic(topic));
  });

  if (hero && "IntersectionObserver" in window) {
    const heroObserver = new IntersectionObserver(([entry]) => {
      heroIsVisible = entry.isIntersecting;
      if (heroIsVisible) scheduleHeroRotation();
      else stopHeroRotation();
    }, { threshold: 0.15 });

    heroObserver.observe(hero);
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopHeroRotation();
    else scheduleHeroRotation();
  });

  if ("addEventListener" in reducedMotion) {
    reducedMotion.addEventListener("change", scheduleHeroRotation);
  }

  window.addEventListener("pagehide", stopHeroRotation);
  window.addEventListener("pageshow", scheduleHeroRotation);
  scheduleHeroRotation();

  const preloadTopicImages = () => {
    ["assets/images/engineering-plans.jpg", "assets/images/music-performance.jpg"].forEach((src) => {
      const image = new Image();
      image.decoding = "async";
      image.src = src;
    });
  };

  window.addEventListener("load", () => {
    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(preloadTopicImages, { timeout: 2500 });
    } else {
      window.setTimeout(preloadTopicImages, 750);
    }
  }, { once: true });

  const revealItems = [...document.querySelectorAll(".reveal")];

  if (reducedMotion.matches || !("IntersectionObserver" in window)) {
    revealItems.forEach((item) => item.classList.add("is-visible"));
  } else {
    const revealObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, {
      rootMargin: "0px 0px -8%",
      threshold: 0.12
    });

    revealItems.forEach((item) => revealObserver.observe(item));
  }

  const sections = sectionLinks
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);
  const navById = new Map(sectionLinks.map((link) => [link.getAttribute("href").slice(1), link]));

  const markCurrentSection = (id) => {
    sectionLinks.forEach((link) => link.removeAttribute("aria-current"));
    navById.get(id)?.setAttribute("aria-current", "location");
  };

  let sectionTicking = false;

  const updateCurrentSection = () => {
    if (!sections.length) {
      sectionTicking = false;
      return;
    }

    const headerOffset = (header?.offsetHeight ?? 0) + 24;
    const marker = window.scrollY + Math.max(headerOffset, window.innerHeight * 0.28);
    let currentId = sections[0]?.id ?? "home";

    sections.forEach((section) => {
      if (section.offsetTop <= marker) currentId = section.id;
    });

    markCurrentSection(currentId);
    sectionTicking = false;
  };

  const requestSectionUpdate = () => {
    if (sectionTicking) return;
    sectionTicking = true;
    window.requestAnimationFrame(updateCurrentSection);
  };

  updateCurrentSection();
  window.addEventListener("scroll", requestSectionUpdate, { passive: true });
  window.addEventListener("resize", requestSectionUpdate);
  window.addEventListener("hashchange", requestSectionUpdate);

  const year = document.querySelector("[data-year]");
  if (year) year.textContent = String(new Date().getFullYear());
})();
