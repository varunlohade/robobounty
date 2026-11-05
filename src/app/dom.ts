// All text enters the page through textContent, so chat and file data can never become markup.
export function el<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const ICONS: Record<string, string[]> = {
  play: ['M8 5v14l11-7z'],
  pause: ['M7 5h4v14H7z', 'M13 5h4v14h-4z'],
  send: ['M12 19V6', 'M6 11l6-6 6 6'],
  start: ['M6 5h2.5v14H6z', 'M19 5v14L9.5 12z'],
  end: ['M15.5 5H18v14h-2.5z', 'M5 5v14l9.5-7z'],
  chevron: ['M9 6l6 6-6 6'],
  plus: ['M12 5v14', 'M5 12h14'],
};

export function icon(name: keyof typeof ICONS, stroke = false): SVGSVGElement {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '16');
  svg.setAttribute('height', '16');
  svg.setAttribute('fill', stroke ? 'none' : 'currentColor');
  if (stroke) { svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '2.5'); }
  for (const d of ICONS[name]) {
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', d);
    svg.appendChild(path);
  }
  return svg;
}
