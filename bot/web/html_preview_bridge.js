(() => {
  const [sessionId, prefix, site, originalCSS] = PREVIEW_OPTIONS;
  // Browser-created relative URLs already resolve against the original document
  // or module. Only move requests addressed to the site's virtual root.
  function siteURL(value) {
    if (typeof value !== "string" && !(value instanceof URL)) return value;
    const text = String(value).trim();
    if (!/^\/(?![/\\])|^https?:\/\//i.test(text)) return value;
    let url;
    try { url = new URL(text, location.href); } catch { return value; }
    if (url.origin !== location.origin || url.pathname.startsWith(prefix)) return value;
    return site + url.pathname.slice(1) + url.search + url.hash;
  }

  const nativeFetch = window.fetch;
  window.fetch = function(input, init) {
    if (input instanceof Request) {
      if (["GET", "HEAD"].includes(input.method)) {
        const mapped = siteURL(input.url);
        if (mapped !== input.url) input = new Request(mapped, input);
      }
    } else {
      input = siteURL(input);
    }
    return nativeFetch.call(this, input, init);
  };
  const openRequest = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...args) {
    return openRequest.call(this, method, siteURL(url), ...args);
  };

  function siteSrcset(value) {
    if (typeof value !== "string") return value;
    const candidate = /[^,\t\n\f\r ][^\t\n\f\r ]*/g;
    const descriptor = /(?:\([^)]*\)|[^,(])*(?:,|$)/y;
    let result = "", end = 0, match;
    while ((match = candidate.exec(value))) {
      const url = match[0].replace(/,+$/, "");
      result += value.slice(end, match.index) + siteURL(url);
      end = match.index + url.length;
      if (url === match[0]) {
        descriptor.lastIndex = candidate.lastIndex;
        if (descriptor.exec(value)) candidate.lastIndex = descriptor.lastIndex;
      }
    }
    return result + value.slice(end);
  }
  function siteCSS(value) {
    if (typeof value !== "string" || !value.includes("/")) return value;
    const tokens = /\/\*[\s\S]*?(?:\*\/|$)|(url\(\s*|@import\s*(?=["']))("(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'|[^\s()'";]+)|"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'/gi;
    return value.replace(tokens, (token, before, target, offset) => {
      if (!before || (offset > 0 && /[\w-]/.test(value[offset - 1]))) return token;
      const quote = /^["']/.test(target) ? target[0] : "";
      const url = quote ? target.slice(1, -1) : target;
      return before + quote + siteURL(url) + quote;
    });
  }
  function linkURL(value) {
    const mapped = siteURL(value);
    if (!(this instanceof HTMLLinkElement) || !this.integrity ||
        !(this.relList.contains("stylesheet") || (this.relList.contains("preload") && this.as === "style"))) return mapped;
    let url;
    try { url = new URL(mapped, document.baseURI); } catch { return mapped; }
    if (url.origin !== location.origin || !url.pathname.startsWith(prefix) || url.searchParams.has(originalCSS)) return mapped;
    url.search += (url.search ? "&" : "?") + originalCSS + "=1";
    return url.href;
  }
  // Let the browser check the original bytes first. Change URL-bearing rules
  // on the verified sheet in place so relative URLs retain the stylesheet base.
  document.addEventListener("load", event => {
    const link = event.target;
    if (!(link instanceof HTMLLinkElement) || !link.integrity || !link.sheet) return;
    try {
      const sheet = link.sheet;
      for (let i = 0; i < sheet.cssRules.length; i++) {
        const css = sheet.cssRules[i].cssText;
        const mapped = siteCSS(css);
        if (mapped !== css) {
          sheet.insertRule(mapped, i);
          sheet.deleteRule(i + 1);
        }
      }
    } catch { /* The browser controls CSSOM access to the sheet. */ }
  }, true);
  const attributes = new Map([
    ["href", linkURL], ["xlink:href", siteURL], ["src", siteURL], ["poster", siteURL],
    ["srcset", siteSrcset], ["imagesrcset", siteSrcset], ["style", siteCSS],
  ]);
  const setAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function(name, value) {
    const map = attributes.get(String(name).toLowerCase());
    return setAttribute.call(this, name, map ? map.call(this, value) : value);
  };
  // Frameworks can set URL properties directly, including on detached images.
  for (const [type, names] of [
    [HTMLImageElement, ["src", "srcset"]], [HTMLScriptElement, ["src"]],
    [HTMLLinkElement, ["href", "imageSrcset"]], [HTMLAnchorElement, ["href"]],
    [HTMLAreaElement, ["href"]], [HTMLBaseElement, ["href"]],
    [HTMLSourceElement, ["src", "srcset"]], [HTMLMediaElement, ["src"]], [HTMLVideoElement, ["poster"]],
  ]) {
    for (const name of names) {
      const property = Object.getOwnPropertyDescriptor(type.prototype, name);
      if (!property?.set || !property.configurable) continue;
      const map = attributes.get(name.toLowerCase());
      Object.defineProperty(type.prototype, name, {
        ...property, set(value) { property.set.call(this, map.call(this, value)); },
      });
    }
  }

  // innerHTML and CSSOM edits do not call JavaScript attribute setters.
  function fixAttribute(element, name) {
    const map = attributes.get(name);
    if (!map) return;
    const value = element.getAttribute(name);
    if (value === null) return;
    const mapped = map.call(element, value);
    if (mapped === value) return;
    const attribute = element.getAttributeNode(name);
    if (attribute.namespaceURI) element.setAttributeNS(attribute.namespaceURI, attribute.name, mapped);
    else setAttribute.call(element, name, mapped);
  }
  function fixStyle(element) {
    if (element?.localName !== "style") return;
    const css = element.textContent;
    const mapped = siteCSS(css);
    if (css !== mapped) element.textContent = mapped;
  }
  function fixElement(element) {
    for (const name of element.getAttributeNames()) fixAttribute(element, name);
    fixStyle(element);
  }
  const selector = "style,[style],[href],[xlink\\:href],[src],[srcset],[imagesrcset],[poster]";
  new MutationObserver(records => {
    const added = new Set();
    for (const record of records) {
      if (record.type === "attributes") {
        if (["rel", "integrity", "as"].includes(record.attributeName)) {
          if (record.target instanceof HTMLLinkElement) fixAttribute(record.target, "href");
        } else {
          fixAttribute(record.target, record.attributeName);
        }
      } else {
        fixStyle(record.target);
        for (const node of record.addedNodes) {
          if (node instanceof Element && node.isConnected) added.add(node);
        }
      }
    }
    for (const node of added) {
      if (added.has(node.parentElement)) continue;
      fixElement(node);
      node.querySelectorAll(selector).forEach(fixElement);
    }
  }).observe(document, {childList: true, subtree: true, attributes: true, attributeFilter: [...attributes.keys(), "rel", "integrity", "as"]});

  const path = () => location.pathname.slice(prefix.length) + location.search + location.hash;
  let failure = "";
  let historyLength = history.length;
  const visited = new Set([location.href]);
  let followingLink = "";
  const send = (event, message) => {
    if (event === "error") failure = message;
    parent.postMessage({type: "orbit-html-preview", sessionId, event: failure && event !== "traverse" ? "error" : event, path: path(), ...(failure ? {message: failure} : {})}, "*");
  };
  addEventListener("message", event => {
    const data = event.data;
    if (event.source === parent && data && data.type === "orbit-html-preview" && data.sessionId === sessionId && data.command === "refresh") location.reload();
  });
  addEventListener("hashchange", () => send("path"));
  addEventListener("click", event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
    const link = event.target?.closest?.("a[href]");
    if (!(link instanceof HTMLAnchorElement) || link.hasAttribute("download")) return;
    const href = link.getAttribute("href");
    const scoped = siteURL(href);
    if (scoped !== href) link.setAttribute("href", scoped);
    const target = link.getAttribute("target") ?? document.querySelector("base[target]")?.target;
    if ((target && target.toLowerCase() !== "_self") || link.origin !== location.origin || !link.pathname.startsWith(prefix)) return;
    followingLink = link.href;
    // Older parent browsers cannot target a top-level history entry by key. Keep ordinary
    // same-frame ticket links usable without adding child-only entries to their Back stack.
    if (window.name === "orbit-preview-replace-" + sessionId) {
      event.preventDefault();
      location.replace(link.href);
    }
  });
  // A new fragment also emits popstate. Back returns to a previously seen URL
  // without extending the joint session history. The parent validates the ticket.
  addEventListener("popstate", () => {
    const traversal = followingLink !== location.href && history.length === historyLength && visited.has(location.href);
    followingLink = "";
    visited.add(location.href);
    historyLength = history.length;
    send("path");
    if (traversal) send("traverse");
  });
  addEventListener("pageshow", event => {
    if (event.persisted || performance.getEntriesByType("navigation")[0]?.type === "back_forward") send("traverse");
  });
  for (const name of ["pushState", "replaceState"]) {
    const original = history[name];
    history[name] = function(...args) {
      if (args.length > 2) args[2] = siteURL(args[2]);
      const result = original.apply(this, args);
      visited.add(location.href);
      historyLength = history.length;
      send("path");
      return result;
    };
  }
  addEventListener("error", event => send("error", event.message || "资源加载失败"), true);
  addEventListener("unhandledrejection", event => send("error", String(event.reason || "页面脚本失败")));
  addEventListener("DOMContentLoaded", () => send("ready"), {once: true});
})();
