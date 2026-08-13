const SAFE_LINK_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

export function renderMarkdown(target, markdown) {
  target.replaceChildren(...parseBlocks(`${markdown ?? ""}`));
}

function parseBlocks(markdown) {
  const lines = markdown.replaceAll("\r\n", "\n").replaceAll("\r", "\n").split("\n");
  const nodes = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^```([A-Za-z0-9_-]+)?\s*$/);
    if (fence) {
      const code = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      nodes.push(codeBlock(code.join("\n"), fence[1] || ""));
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6);
      nodes.push(withInlineText(document.createElement(`h${level}`), heading[2]));
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      const { table, nextIndex } = parseTable(lines, index);
      nodes.push(table);
      index = nextIndex;
      continue;
    }

    if (isListLine(line)) {
      const { list, nextIndex } = parseList(lines, index);
      nodes.push(list);
      index = nextIndex;
      continue;
    }

    const paragraph = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^```/.test(lines[index]) &&
      !/^(#{1,4})\s+/.test(lines[index]) &&
      !isListLine(lines[index]) &&
      !isTableStart(lines, index)
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    nodes.push(withInlineText(document.createElement("p"), paragraph.join("\n")));
  }
  return nodes.length ? nodes : [document.createElement("p")];
}

function codeBlock(code, language) {
  const wrapper = document.createElement("div");
  wrapper.className = "markdown-code-scroll";
  const pre = document.createElement("pre");
  const codeNode = document.createElement("code");
  if (language) codeNode.dataset.language = language;
  codeNode.textContent = code;
  pre.append(codeNode);
  wrapper.append(pre);
  return wrapper;
}

function isListLine(line) {
  return /^(\s*)([-*+]|\d+[.)])\s+/.test(line);
}

function parseList(lines, startIndex) {
  const ordered = /^\s*\d+[.)]\s+/.test(lines[startIndex]);
  const list = document.createElement(ordered ? "ol" : "ul");
  let index = startIndex;
  while (index < lines.length && isListLine(lines[index])) {
    const text = lines[index].replace(/^\s*([-*+]|\d+[.)])\s+/, "");
    list.append(withInlineText(document.createElement("li"), text));
    index += 1;
  }
  return { list, nextIndex: index };
}

function isTableStart(lines, index) {
  return (
    index + 1 < lines.length &&
    splitTableRow(lines[index]).length > 1 &&
    /^:?-{3,}:?(\s*\|\s*:?-{3,}:?)*\s*\|?\s*$/.test(stripEdgePipes(lines[index + 1]))
  );
}

function parseTable(lines, startIndex) {
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const tbody = document.createElement("tbody");
  const headers = splitTableRow(lines[startIndex]);
  const headerRow = document.createElement("tr");
  headers.forEach((header) => {
    headerRow.append(withInlineText(document.createElement("th"), header.trim()));
  });
  thead.append(headerRow);
  let index = startIndex + 2;
  while (index < lines.length && splitTableRow(lines[index]).length > 1) {
    const row = document.createElement("tr");
    splitTableRow(lines[index]).forEach((cell) => {
      row.append(withInlineText(document.createElement("td"), cell.trim()));
    });
    tbody.append(row);
    index += 1;
  }
  table.append(thead, tbody);
  const wrapper = document.createElement("div");
  wrapper.className = "markdown-table-scroll";
  wrapper.append(table);
  return { table: wrapper, nextIndex: index };
}

function stripEdgePipes(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "");
}

function splitTableRow(line) {
  return stripEdgePipes(line).split("|");
}

function withInlineText(element, text) {
  element.append(...parseInline(text));
  return element;
}

function parseInline(text) {
  const fragment = [];
  let index = 0;
  const tokenPattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;
  for (const match of text.matchAll(tokenPattern)) {
    if (match.index > index) fragment.push(document.createTextNode(text.slice(index, match.index)));
    fragment.push(inlineToken(match[0]));
    index = match.index + match[0].length;
  }
  if (index < text.length) fragment.push(document.createTextNode(text.slice(index)));
  return fragment;
}

function inlineToken(token) {
  if (token.startsWith("`") && token.endsWith("`")) {
    const code = document.createElement("code");
    code.textContent = token.slice(1, -1);
    return code;
  }
  if (token.startsWith("**") && token.endsWith("**")) {
    return withInlineText(document.createElement("strong"), token.slice(2, -2));
  }
  const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
  if (link) {
    const anchor = withInlineText(document.createElement("a"), link[1]);
    const href = safeHref(link[2]);
    if (!href) return document.createTextNode(link[1]);
    anchor.href = href;
    anchor.target = "_blank";
    anchor.rel = "noreferrer";
    return anchor;
  }
  return document.createTextNode(token);
}

function safeHref(value) {
  try {
    const url = new URL(value, window.location.href);
    return SAFE_LINK_PROTOCOLS.has(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}
