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

  const createSiteSearch = () => {
    if (!nav || document.querySelector("[data-search-trigger]")) return;

    const pageName = window.location.pathname.split("/").pop()?.toLowerCase() ?? "";
    const onMainPage = pageName === "" || pageName === "index.html";
    const mainSectionHref = (id) => onMainPage ? `#${id}` : `index.html#${id}`;
    const searchDestinations = [
      { label: "Home", meta: "Overview", href: mainSectionHref("home"), keywords: "home start introduction overview" },
      { label: "Surveying", meta: "Field & CADD", href: "surveying.html", keywords: "surveying field geomatics cadd construction recording" },
      { label: "Engineering", meta: "Civil design", href: "engineering.html", keywords: "engineering civil plans drafting as-builts land development" },
      { label: "Music", meta: "Performance", href: "music.html", keywords: "music percussion performance leadership paradigm" },
      { label: "About", meta: "Background", href: mainSectionHref("about"), keywords: "about biography background credentials goals" },
      { label: "Résumé", meta: "Experience", href: mainSectionHref("resume"), keywords: "resume résumé experience education credentials pdf" },
      { label: "Contact", meta: "Connect", href: mainSectionHref("contact"), keywords: "contact email linkedin connect message" },
      { label: "Send a message", meta: "Email draft", href: mainSectionHref("message"), keywords: "send message form email draft contact" },
      { label: "Open résumé PDF", meta: "Document ↗", href: "assets/documents/caden-trahan-resume.pdf", keywords: "open download resume résumé pdf document", newTab: true }
    ];

    const searchTrigger = document.createElement("button");
    searchTrigger.className = "site-search-trigger";
    searchTrigger.type = "button";
    searchTrigger.dataset.searchTrigger = "";
    searchTrigger.setAttribute("aria-haspopup", "dialog");
    searchTrigger.setAttribute("aria-controls", "site-search-dialog");
    searchTrigger.setAttribute("aria-expanded", "false");
    searchTrigger.setAttribute("aria-label", "Search the portfolio");
    searchTrigger.innerHTML = `
      <span class="search-icon" aria-hidden="true"></span>
      <span class="site-search-trigger__label">Search</span>
      <kbd aria-hidden="true">Ctrl K</kbd>
    `;
    nav.insertAdjacentElement("afterend", searchTrigger);

    const searchDialog = document.createElement("dialog");
    searchDialog.className = "search-dialog";
    searchDialog.id = "site-search-dialog";
    searchDialog.dataset.searchDialog = "";
    searchDialog.setAttribute("aria-labelledby", "site-search-title");
    searchDialog.innerHTML = `
      <div class="search-dialog__surface">
        <div class="search-dialog__field">
          <span class="search-icon" aria-hidden="true"></span>
          <label class="sr-only" for="site-search-input">Search pages, sections, and actions</label>
          <input id="site-search-input" type="search" inputmode="search" autocomplete="off" spellcheck="false" role="combobox" aria-autocomplete="list" aria-controls="site-search-results" aria-expanded="false" placeholder="Jump to a page, section, or action…" data-search-input>
          <button class="search-dialog__close" type="button" data-search-close aria-label="Close search"><kbd aria-hidden="true">Esc</kbd></button>
        </div>
        <div class="search-dialog__body">
          <p class="search-dialog__label mono" id="site-search-title">Go to</p>
          <nav class="search-results" id="site-search-results" role="listbox" aria-label="Search destinations" data-search-results>
            ${searchDestinations.map((item, index) => `
              <a id="site-search-option-${index}" role="option" aria-selected="false" href="${item.href}" data-search-item data-search-text="${item.label} ${item.meta} ${item.keywords}"${item.newTab ? ' target="_blank" rel="noopener"' : ""}>
                <span>${item.label}</span>
                <small class="mono">${item.meta}</small>
              </a>
            `).join("")}
          </nav>
          <p class="search-dialog__empty" data-search-empty hidden>No matching destination.</p>
          <p class="sr-only" data-search-status role="status" aria-live="polite" aria-atomic="true"></p>
        </div>
        <div class="search-dialog__footer mono" aria-hidden="true">
          <span>↑ ↓ navigate</span>
          <span>Enter select</span>
          <span>Esc close</span>
        </div>
      </div>
    `;
    document.body.append(searchDialog);

    const searchInput = searchDialog.querySelector("[data-search-input]");
    const searchClose = searchDialog.querySelector("[data-search-close]");
    const searchEmpty = searchDialog.querySelector("[data-search-empty]");
    const searchStatus = searchDialog.querySelector("[data-search-status]");
    const searchItems = [...searchDialog.querySelectorAll("[data-search-item]")];
    let activeSearchItem = null;
    let restoreSearchFocus = true;
    let focusAfterSearchClose = null;

    const normalizeSearch = (value) => value
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();

    const getVisibleSearchItems = () => searchItems.filter((item) => !item.hidden);
    const isSearchOpen = () => searchDialog.open || searchDialog.hasAttribute("open");

    const setActiveSearchItem = (item) => {
      searchItems.forEach((searchItem) => {
        const isActive = searchItem === item;
        searchItem.classList.toggle("is-active", isActive);
        searchItem.setAttribute("aria-selected", String(isActive));
      });
      activeSearchItem = item ?? null;
      if (activeSearchItem) searchInput.setAttribute("aria-activedescendant", activeSearchItem.id);
      else searchInput.removeAttribute("aria-activedescendant");
      activeSearchItem?.scrollIntoView({ block: "nearest" });
    };

    const filterSearchItems = () => {
      const query = normalizeSearch(searchInput?.value ?? "");

      searchItems.forEach((item) => {
        item.hidden = query !== "" && !normalizeSearch(item.dataset.searchText ?? "").includes(query);
      });

      const visibleItems = getVisibleSearchItems();
      if (searchEmpty) searchEmpty.hidden = visibleItems.length > 0;
      if (searchStatus) {
        searchStatus.textContent = visibleItems.length === 1
          ? "1 destination available."
          : `${visibleItems.length} destinations available.`;
      }
      setActiveSearchItem(visibleItems[0] ?? null);
    };

    const finishSearchClose = () => {
      document.body.classList.remove("search-open");
      searchTrigger.setAttribute("aria-expanded", "false");
      searchInput.setAttribute("aria-expanded", "false");

      if (focusAfterSearchClose instanceof HTMLElement) {
        window.requestAnimationFrame(() => focusAfterSearchClose.focus({ preventScroll: true }));
      } else if (restoreSearchFocus) {
        searchTrigger.focus({ preventScroll: true });
      }

      restoreSearchFocus = true;
      focusAfterSearchClose = null;
    };

    const closeSearch = ({ restoreFocus = true, focusTarget = null } = {}) => {
      restoreSearchFocus = restoreFocus;
      focusAfterSearchClose = focusTarget;

      if (typeof searchDialog.close === "function" && isSearchOpen()) {
        searchDialog.close();
      } else {
        searchDialog.removeAttribute("open");
        finishSearchClose();
      }
    };

    const openSearch = () => {
      setNavOpen(false);
      if (isSearchOpen()) return;

      searchInput.value = "";
      filterSearchItems();
      searchTrigger.setAttribute("aria-expanded", "true");
      searchInput.setAttribute("aria-expanded", "true");
      document.body.classList.add("search-open");

      if (typeof searchDialog.showModal === "function") searchDialog.showModal();
      else searchDialog.setAttribute("open", "");

      window.requestAnimationFrame(() => searchInput.focus());
    };

    searchTrigger.addEventListener("click", openSearch);
    searchClose?.addEventListener("click", () => closeSearch());
    searchDialog.addEventListener("close", finishSearchClose);
    searchDialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeSearch();
    });
    searchDialog.addEventListener("click", (event) => {
      if (event.target === searchDialog) closeSearch();
    });

    searchInput?.addEventListener("input", filterSearchItems);
    searchInput?.addEventListener("keydown", (event) => {
      const visibleItems = getVisibleSearchItems();
      if (!visibleItems.length) return;

      const currentIndex = Math.max(0, visibleItems.indexOf(activeSearchItem));

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveSearchItem(visibleItems[(currentIndex + 1) % visibleItems.length]);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveSearchItem(visibleItems[(currentIndex - 1 + visibleItems.length) % visibleItems.length]);
      } else if (event.key === "Enter" && activeSearchItem) {
        event.preventDefault();
        activeSearchItem.click();
      }
    });

    searchItems.forEach((item) => {
      item.addEventListener("pointerenter", () => setActiveSearchItem(item));
      item.addEventListener("focus", () => setActiveSearchItem(item));
      item.addEventListener("click", () => {
        const itemUrl = new URL(item.href, window.location.href);
        const currentUrl = new URL(window.location.href);
        const sameDocumentTarget = itemUrl.origin === currentUrl.origin
          && itemUrl.pathname === currentUrl.pathname
          && itemUrl.search === currentUrl.search
          && itemUrl.hash;
        const destination = sameDocumentTarget ? document.querySelector(itemUrl.hash) : null;
        const destinationFocus = destination?.querySelector("h1, h2, h3") ?? destination;

        if (destinationFocus instanceof HTMLElement) destinationFocus.setAttribute("tabindex", "-1");
        closeSearch({
          restoreFocus: item.target === "_blank",
          focusTarget: destinationFocus
        });
      });
    });

    searchDialog.addEventListener("keydown", (event) => {
      if (event.key !== "Tab" || typeof searchDialog.showModal === "function") return;

      const fallbackFocusable = [searchInput, searchClose, ...getVisibleSearchItems()].filter(Boolean);
      const first = fallbackFocusable[0];
      const last = fallbackFocusable.at(-1);

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    });

    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (isSearchOpen()) closeSearch();
        else openSearch();
      } else if (event.key === "Escape" && isSearchOpen() && typeof searchDialog.showModal !== "function") {
        event.preventDefault();
        closeSearch();
      }
    });
  };

  createSiteSearch();

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

  const contactForm = document.querySelector("[data-contact-form]");
  const formStatus = contactForm?.querySelector("[data-form-status]");
  const contactName = contactForm?.elements.namedItem("name");
  const contactEmail = contactForm?.elements.namedItem("email");
  const contactMessage = contactForm?.elements.namedItem("message");

  const setTrimmedValidity = (field, message) => {
    if (!(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement)) return;
    field.setCustomValidity(field.value.trim() ? "" : message);
  };

  contactName?.addEventListener("input", () => setTrimmedValidity(contactName, "Please enter your name."));
  contactMessage?.addEventListener("input", () => setTrimmedValidity(contactMessage, "Please enter a message."));

  contactForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    setTrimmedValidity(contactName, "Please enter your name.");
    setTrimmedValidity(contactMessage, "Please enter a message.");

    if (!contactForm.reportValidity()) return;

    const name = contactName.value.trim().replace(/[\r\n]+/g, " ");
    const email = contactEmail.value.trim();
    const message = contactMessage.value.trim();
    const recipient = contactForm.dataset.recipient;
    const subject = `Portfolio message from ${name}`;
    const body = `Name: ${name}\nEmail: ${email}\n\nMessage:\n${message}`;

    if (formStatus) {
      formStatus.textContent = "Your email app should open with a prepared draft. Review it, then press send.";
    }

    window.location.href = `mailto:${recipient}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  });

  const year = document.querySelector("[data-year]");
  if (year) year.textContent = String(new Date().getFullYear());
})();
