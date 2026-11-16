/*
 * OpenAqua Harness workbench welcome panel.
 *
 * Injected into the branded web bundle by scripts/sync-web-ui.mjs. Renders a
 * first-run welcome panel (positioning line, three getting-started steps, and
 * four water-treatment starter prompts) into the empty chat state. Clicking a
 * starter card loads its full prompt into the composer and focuses it; sending
 * stays a deliberate user action.
 *
 * Defensive by contract: the upstream bundle is minified and can change, so
 * every hook is presence-checked and the addon silently no-ops when the
 * expected DOM is absent. Rendering is idempotent and the panel removes
 * itself as soon as the empty state disappears.
 */
(function () {
  'use strict';

  var PANEL_ID = 'oa-welcome';

  var COPY = {
    en: {
      ledePrefix: 'Evidence-grounded early-stage process-train design',
      ledeStrong: 'start from a real scenario below',
      ledeSuffix: 'or describe your own.',
      steps: [
        'Set up model',
        'Ask a research question',
        'Review evidence & constraints',
      ],
      hint: 'Choose a scenario to add it to your draft. Review and send when you are ready.',
      insertFailed: 'Could not add the scenario. Please enter it in the composer manually.',
      cite: {
        label: 'How to cite',
        short: 'Liu H. et al. (2027). OpenAqua. Water Research 308, 126761.',
        doiLabel: 'doi:10.1016/j.watres.2026.126761',
        doiUrl: 'https://doi.org/10.1016/j.watres.2026.126761',
        docsLabel: 'About the science',
        docsUrl:
          'https://github.com/zhaorui-bi/OpenAqua-Harness/blob/main/docs/OPENAQUA.md',
        copy: 'Copy citation',
        copied: 'Copied ✓',
        copyFailed: 'Could not copy. Select the text below and copy it manually.',
        plain:
          'Liu H., Jiang Z., Zhong H., Li J., Pang W., Yuan Y. (2027). OpenAqua: An ' +
          'automated multi-agent framework for early-stage water treatment train design ' +
          'with retrieval augmentation and critic-based refinement. Water Research 308, ' +
          '126761. https://doi.org/10.1016/j.watres.2026.126761',
        bibtex:
          '@article{liu2027openaqua,\n' +
          '  title = {OpenAqua: An automated multi-agent framework for early-stage water ' +
          'treatment train design with retrieval augmentation and critic-based ' +
          'refinement},\n' +
          '  author = {Liu, Hanzhang and Jiang, Zhaorui and Zhong, Huiling and Li, ' +
          'Jinshuo and Pang, Wei and Yuan, Yingfang},\n' +
          '  journal = {Water Research},\n' +
          '  volume = {308},\n' +
          '  pages = {126761},\n' +
          '  year = {2027},\n' +
          '  doi = {10.1016/j.watres.2026.126761},\n' +
          '  url = {https://doi.org/10.1016/j.watres.2026.126761}\n' +
          '}',
      },
      starters: [
        {
          title: 'Arsenic in groundwater',
          prompt:
            'Assess arsenic-contaminated groundwater: influent 150 µg/L; target ≤10 µg/L; ' +
            'drinking-water use. Compare three treatment trains for a low-budget, ' +
            'low-maintenance site with no brine disposal. First identify missing case data, ' +
            'then retrieve evidence and report constraints and uncertainty.',
        },
        {
          title: 'DBP control comparison',
          prompt:
            'Compare coagulation–sand filtration versus ultrafiltration for disinfection ' +
            'by-product control at a surface-water plant with high natural organic matter. ' +
            'Report trade-offs in NOM removal, chemical dose, energy, and footprint.',
        },
        {
          title: 'Industrial water reuse',
          prompt:
            'Evaluate treatment trains for reclaiming municipal wastewater as industrial ' +
            'cooling makeup: focus on scaling risk, reverse-osmosis recovery, and ' +
            'concentrate management under a reuse permit.',
        },
        {
          title: 'Rural community supply',
          prompt:
            'Propose a low-maintenance decentralized treatment option for a 500-person ' +
            'rural community with intermittent power and high operator turnover. Justify ' +
            'operability, operator skill requirements, and lifecycle cost.',
        },
      ],
    },
    zh: {
      ledePrefix: '面向循证的早期工艺路线设计',
      ledeStrong: '从下面的真实场景出发',
      ledeSuffix: '，或描述你自己的课题。',
      steps: ['配置模型', '提出研究问题', '审阅证据与约束'],
      hint: '点击场景添加到草稿，确认或修改后再发送。',
      insertFailed: '无法添加场景，请手动输入到编辑框。',
      cite: {
        label: '如何引用',
        short: 'Liu H. 等（2027）. OpenAqua. Water Research 308, 126761.',
        doiLabel: 'doi:10.1016/j.watres.2026.126761',
        doiUrl: 'https://doi.org/10.1016/j.watres.2026.126761',
        docsLabel: '了解 OpenAqua 原理',
        docsUrl:
          'https://github.com/zhaorui-bi/OpenAqua-Harness/blob/main/docs/OPENAQUA.md',
        copy: '复制引用',
        copied: '已复制 ✓',
        copyFailed: '复制失败，请选中下方文字手动复制。',
        plain:
          'Liu H., Jiang Z., Zhong H., Li J., Pang W., Yuan Y. (2027). OpenAqua: An ' +
          'automated multi-agent framework for early-stage water treatment train design ' +
          'with retrieval augmentation and critic-based refinement. Water Research 308, ' +
          '126761. https://doi.org/10.1016/j.watres.2026.126761',
        bibtex:
          '@article{liu2027openaqua,\n' +
          '  title = {OpenAqua: An automated multi-agent framework for early-stage water ' +
          'treatment train design with retrieval augmentation and critic-based ' +
          'refinement},\n' +
          '  author = {Liu, Hanzhang and Jiang, Zhaorui and Zhong, Huiling and Li, ' +
          'Jinshuo and Pang, Wei and Yuan, Yingfang},\n' +
          '  journal = {Water Research},\n' +
          '  volume = {308},\n' +
          '  pages = {126761},\n' +
          '  year = {2027},\n' +
          '  doi = {10.1016/j.watres.2026.126761},\n' +
          '  url = {https://doi.org/10.1016/j.watres.2026.126761}\n' +
          '}',
      },
      starters: [
        {
          title: '地下水砷污染',
          prompt:
            '评估砷污染地下水：进水 150 µg/L，目标 ≤10 µg/L，饮用水用途。针对预算有限、' +
            '维护力量薄弱、无浓盐水处置条件的场地，比较三条处理工艺路线。先指出缺失的' +
            '案例数据，再检索证据，报告约束条件与不确定性。',
        },
        {
          title: '消毒副产物控制对比',
          prompt:
            '对比混凝–砂滤与超滤在高天然有机物地表水厂控制消毒副产物的效果，报告' +
            'NOM 去除、药耗、能耗与占地之间的权衡。',
        },
        {
          title: '工业回用',
          prompt:
            '评估将市政污水再生为工业冷却补水的工艺路线，重点关注结垢风险、反渗透' +
            '回收率与浓水管理（以回用许可为边界条件）。',
        },
        {
          title: '农村供水',
          prompt:
            '为一座 500 人、电力供应不稳定、运维人员流动大的农村社区提出低维护分散式' +
            '处理方案，论证可操作性、人员技能要求与全生命周期成本。',
        },
      ],
    },
  };

  function copyForDocument() {
    var lang;
    try { lang = window.localStorage.getItem('kimi-locale'); } catch (_err) { lang = null; }
    if (lang !== 'en' && lang !== 'zh') lang = navigator.language || document.documentElement.lang || '';
    return lang.toLowerCase().indexOf('zh') === 0 ? COPY.zh : COPY.en;
  }

  function findEmptyState() {
    return document.querySelector('.chat .chat-empty') || document.querySelector('.chat-empty');
  }

  // The upstream empty state renders the logo inside `.chat-empty` while the
  // empty composer (`.empty-composer`) lives in a SIBLING subtree, so the
  // composer must be located from the document, never inside `.chat-empty`.
  function findEmptyComposer() {
    var candidates = document.querySelectorAll('.empty-composer');
    for (var i = 0; i < candidates.length; i += 1) {
      if (candidates[i].getClientRects().length > 0) return candidates[i];
    }
    return candidates.length > 0 ? candidates[0] : null;
  }

  function findComposerEditor() {
    var composer = document.querySelector('.chat-empty .empty-composer') ||
      document.querySelector('.empty-composer') ||
      document.querySelector('.composer');
    if (!composer) return null;
    return composer.querySelector('[contenteditable="true"]') ||
      composer.querySelector('textarea');
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function buildPanel(copy) {
    var panel = el('section', 'oa-welcome');
    panel.id = PANEL_ID;
    panel.setAttribute('aria-label', copy.ledePrefix);
    panel.setAttribute('data-language', copy === COPY.zh ? 'zh' : 'en');

    var lede = el('p', 'oa-welcome-lede');
    lede.appendChild(document.createTextNode(copy.ledePrefix + ' — '));
    lede.appendChild(el('strong', '', copy.ledeStrong));
    lede.appendChild(document.createTextNode(' ' + copy.ledeSuffix));
    panel.appendChild(lede);

    var steps = el('ol', 'oa-welcome-steps');
    copy.steps.forEach(function (label, index) {
      var step = el('li', 'oa-welcome-step' + (index === 0 ? ' is-first' : ''));
      step.appendChild(el('span', 'oa-welcome-step-n', String(index + 1)));
      step.appendChild(el('span', 'oa-welcome-step-label', label));
      steps.appendChild(step);
    });
    panel.appendChild(steps);

    var hint = el('p', 'oa-welcome-hint', copy.hint);
    hint.setAttribute('role', 'status');
    var cards = el('div', 'oa-welcome-cards');
    copy.starters.forEach(function (starter) {
      var card = el('button', 'oa-welcome-card');
      card.type = 'button';
      var heading = el('h4', 'oa-welcome-card-title');
      heading.appendChild(el('span', 'oa-welcome-card-dot'));
      heading.appendChild(el('span', '', starter.title));
      card.appendChild(heading);
      card.appendChild(el('p', 'oa-welcome-card-prompt', starter.prompt));
      card.addEventListener('click', function () {
        hint.textContent = loadIntoComposer(starter.prompt) ? copy.hint : copy.insertFailed;
      });
      cards.appendChild(card);
    });
    panel.appendChild(cards);

    panel.appendChild(hint);

    var cite = el('div', 'oa-welcome-cite');
    var citeHead = el('div', 'oa-welcome-cite-head');
    citeHead.appendChild(el('span', 'oa-welcome-cite-label', copy.cite.label));
    var doiLink = el('a', 'oa-welcome-cite-link', copy.cite.doiLabel);
    doiLink.href = copy.cite.doiUrl;
    doiLink.target = '_blank';
    doiLink.rel = 'noreferrer';
    citeHead.appendChild(doiLink);
    var docsLink = el('a', 'oa-welcome-cite-link', copy.cite.docsLabel);
    docsLink.href = copy.cite.docsUrl;
    docsLink.target = '_blank';
    docsLink.rel = 'noreferrer';
    citeHead.appendChild(docsLink);
    cite.appendChild(citeHead);
    cite.appendChild(el('p', 'oa-welcome-cite-text', copy.cite.short));
    var copyRow = el('div', 'oa-welcome-cite-actions');
    var copyStatus = el('p', 'oa-welcome-cite-text');
    copyStatus.setAttribute('role', 'status');
    var manualCopy = el('textarea', 'oa-welcome-cite-manual');
    manualCopy.setAttribute('readonly', '');
    manualCopy.rows = 5;
    manualCopy.setAttribute('aria-label', copy.cite.copy);
    manualCopy.hidden = true;
    var plainButton = el('button', 'oa-welcome-cite-btn', copy.cite.copy);
    plainButton.type = 'button';
    plainButton.addEventListener('click', function () {
      copyCitation(plainButton, copy.cite.plain, copy.cite, copyStatus, manualCopy);
    });
    var bibtexButton = el('button', 'oa-welcome-cite-btn', 'BibTeX');
    bibtexButton.type = 'button';
    bibtexButton.addEventListener('click', function () {
      copyCitation(bibtexButton, copy.cite.bibtex, copy.cite, copyStatus, manualCopy);
    });
    copyRow.appendChild(plainButton);
    copyRow.appendChild(bibtexButton);
    cite.appendChild(copyRow);
    cite.appendChild(copyStatus);
    cite.appendChild(manualCopy);
    panel.appendChild(cite);
    return panel;
  }

  function copyCitation(button, text, copy, status, manualCopy) {
    var finish = function (success) {
      if (!success) {
        status.textContent = copy.copyFailed;
        manualCopy.value = text;
        manualCopy.hidden = false;
        manualCopy.focus();
        manualCopy.select();
        return;
      }
      status.textContent = copy.copied;
      manualCopy.hidden = true;
      button.classList.add('is-copied');
      setTimeout(function () { button.classList.remove('is-copied'); }, 1600);
    };
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      navigator.clipboard.writeText(text).then(function () { finish(true); }, function () {
        finish(fallbackCopy(text));
      });
    } else {
      finish(fallbackCopy(text));
    }
  }

  function fallbackCopy(text) {
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.top = '-9999px';
    document.body.appendChild(area);
    area.select();
    var copied = false;
    try {
      copied = document.execCommand('copy');
    } catch (_err) {
      copied = false;
    }
    document.body.removeChild(area);
    return copied;
  }

  function loadIntoComposer(prompt) {
    var editor = findComposerEditor();
    if (!editor) return false;
    var existing = typeof editor.value === 'string' ? editor.value : editor.textContent;
    var insertion = existing && existing.trim() ? '\n\n' + prompt : prompt;
    editor.focus();
    if (typeof editor.value === 'string') {
      var end = editor.value.length;
      if (typeof editor.setSelectionRange === 'function') editor.setSelectionRange(end, end);
    } else {
      var selection = window.getSelection();
      if (!selection) return false;
      var range = document.createRange();
      range.selectNodeContents(editor);
      range.collapse(false);
      selection.removeAllRanges();
      selection.addRange(range);
    }
    try {
      if (document.execCommand('insertText', false, insertion)) return true;
    } catch (_err) {
      // Fall back for plain text inputs; rich editors must handle their own state.
    }
    if (typeof editor.value === 'string') {
      var setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(editor), 'value');
      if (setter && setter.set) setter.set.call(editor, editor.value + insertion);
      else editor.value += insertion;
      editor.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    }
    return false;
  }

  function removePanel() {
    var panel = document.getElementById(PANEL_ID);
    if (panel && panel.parentNode) panel.parentNode.removeChild(panel);
  }

  function sync() {
    var composer = findEmptyComposer();
    var emptyState = composer ? null : findEmptyState();
    if (!composer && !emptyState) {
      removePanel();
      return;
    }
    var existingPanel = document.getElementById(PANEL_ID);
    var language = copyForDocument() === COPY.zh ? 'zh' : 'en';
    if (existingPanel && existingPanel.getAttribute('data-language') === language) return;
    if (existingPanel) removePanel();
    if (composer && composer.parentNode) {
      // Insert as the container's first child so the order reads
      // logo → examples → workspace selector → composer. Anchoring right
      // before the composer instead leaves the selector stranded above the
      // examples, which reads upside-down.
      composer.parentNode.insertBefore(buildPanel(copyForDocument()), composer.parentNode.firstChild);
      return;
    }
    // Fallback for variant structures: anchor right after the logo block.
    if (emptyState && emptyState.parentNode) {
      emptyState.parentNode.insertBefore(
        buildPanel(copyForDocument()),
        emptyState.nextSibling,
      );
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', sync);
  } else {
    sync();
  }

  var scheduled = false;
  var observer = new MutationObserver(function () {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(function () {
      scheduled = false;
      sync();
    });
  });
  if (document.body) {
    observer.observe(document.body, { childList: true, characterData: true, subtree: true });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
  } else {
    document.addEventListener('DOMContentLoaded', function () {
      observer.observe(document.body, { childList: true, characterData: true, subtree: true });
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    });
  }
})();
