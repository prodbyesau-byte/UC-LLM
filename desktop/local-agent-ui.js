(function () {
    'use strict';

    function bootstrapTheme() {
        const initialized = localStorage.getItem('n2llm-theme-initialized');
        const stored = initialized ? localStorage.getItem('n2llm-theme-mode') : 'dark';
        const mode = ['warm-light', 'dark', 'system'].includes(stored) ? stored : 'dark';
        const resolved = mode === 'system'
            ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'warm-light')
            : mode;
        document.documentElement.dataset.themeMode = mode;
        document.documentElement.dataset.theme = resolved;
        localStorage.setItem('n2llm-theme-mode', mode);
        localStorage.setItem('n2llm-theme-initialized', '1');
    }

    bootstrapTheme();

    function stripSillyTavernAssistant() {
        document.querySelectorAll('.mes').forEach((message) => {
            const text = (message.textContent || '').replace(/\s+/g, ' ').toLowerCase();
            if (text.includes("if you're connected to an api") ||
                text.includes('set any character as your welcome page assistant')) {
                message.remove();
            }
        });
        document.querySelectorAll('.welcomeShortcuts, .welcomeButtons').forEach((shortcuts) => shortcuts.remove());
        document.querySelectorAll('#chat button, #chat a').forEach((element) => {
            const label = (element.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
            if (['api connections', 'character management', 'extensions'].includes(label)) {
                element.remove();
            }
        });
    }

    function customizeRecentProjects() {
        document.querySelectorAll('.noRecentChat').forEach((emptyState) => {
            const label = emptyState.querySelector('[data-i18n="No recent chats"]');
            if (label) {
                label.textContent = 'No recent projects';
                label.dataset.i18n = 'No recent projects';
            }
            const icon = emptyState.querySelector('i.fa-comment-dots, i.fa-comments, i.fa-comment');
            if (icon) {
                icon.className = 'fa-solid fa-folder-tree';
                icon.setAttribute('aria-label', 'Project');
            }
        });
    }

    customizeRecentProjects();
    window.setInterval(customizeRecentProjects, 500);

    window.setInterval(stripSillyTavernAssistant, 500);
    stripSillyTavernAssistant();

    function releaseStuckSplash() {
        document.querySelectorAll('.splash-screen, #preloader, .loader-overlay').forEach((element) => {
            element.remove();
        });
        document.body.classList.remove('loading', 'preloader');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.setTimeout(releaseStuckSplash, 3500);
        }, { once: true });
    } else {
        window.setTimeout(releaseStuckSplash, 3500);
    }

    function first(selectors) {
        for (const selector of selectors) {
            const element = document.querySelector(selector);
            if (element) return element;
        }
        return null;
    }

    function closePanels() {
        document.querySelectorAll('.drawer-content, #left-nav-panel, #right-nav-panel, #local-agent-files').forEach((panel) => {
            panel.classList.remove('openDrawer');
            panel.classList.remove('open');
        });
        document.body.classList.remove('drawer-open');
    }

    function ensurePages() {
        let pages = document.querySelector('#local-agent-pages');
        if (pages) return pages;
        pages = document.createElement('main');
        pages.id = 'local-agent-pages';
        pages.innerHTML =
            '<section class="local-agent-page" data-page="profile">' +
                '<div class="local-agent-page-heading"><span class="local-agent-eyebrow">N2LLM</span><h1>Profile</h1><p>Your local assistant identity and personalization.</p></div>' +
                '<div class="local-agent-page-grid">' +
                    '<article class="local-agent-page-card"><div class="local-agent-avatar">LA</div><h2>LOCAL AGENT</h2><p>Private local assistant</p></article>' +
                    '<article class="local-agent-page-card"><h2>Persona</h2><p>Choose how your assistant presents itself in chat.</p><button type="button" class="local-agent-action" data-open-profile>Open persona settings</button></article>' +
                '</div>' +
            '</section>' +
            '<section class="local-agent-page" data-page="settings">' +
                '<div class="local-agent-page-heading"><span class="local-agent-eyebrow">N2LLM</span><h1>Settings</h1><p>Manage the local assistant without leaving this page.</p></div>' +
                '<div class="local-agent-page-grid">' +
                    '<article class="local-agent-page-card"><h2>Appearance</h2><label class="local-agent-theme-label" for="local-agent-theme">Theme</label><select id="local-agent-theme"><option value="warm-light">Warm Light</option><option value="dark">Dark</option><option value="system">System</option></select></article>' +
                    '<article class="local-agent-page-card"><h2>Connection</h2><p>Local model API and web services are managed by the desktop app.</p><span class="local-agent-status">LOCAL SERVICES ACTIVE</span></article>' +
                    '<article class="local-agent-page-card"><h2>Tools &amp; Files</h2><p>File tools, indexing, documents and audio analysis are available through the local tool service.</p><button type="button" class="local-agent-action" data-open-settings>Open advanced settings</button></article>' +
                '</div>' +
            '</section>';
        document.body.appendChild(pages);
        installThemeControl(pages.querySelector('#local-agent-theme'));
        pages.querySelector('[data-open-profile]').addEventListener('click', () => {
            const button = first(['#persona_management_button', '#persona-management-button', '#user_avatar_block', '#avatar_upload']);
            if (button) button.click();
        });
        pages.querySelector('[data-open-settings]').addEventListener('click', () => {
            const holder = document.querySelector('#top-settings-holder');
            const button = holder && holder.querySelector('.drawer-icon');
            if (button) button.click();
        });
        return pages;
    }

    function applyTheme(mode) {
        const selected = ['warm-light', 'dark', 'system'].includes(mode) ? mode : 'warm-light';
        const resolved = selected === 'system'
            ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'warm-light')
            : selected;
        document.documentElement.dataset.themeMode = selected;
        document.documentElement.dataset.theme = resolved;
        localStorage.setItem('n2llm-theme-mode', selected);
    }

    function installThemeControl(select) {
        const mode = localStorage.getItem('n2llm-theme-mode') || 'dark';
        applyTheme(mode);
        if (!select) return;
        select.value = mode;
        select.addEventListener('change', () => applyTheme(select.value));
        const media = window.matchMedia('(prefers-color-scheme: dark)');
        const listener = () => {
            if (localStorage.getItem('n2llm-theme-mode') === 'system') applyTheme('system');
        };
        if (media.addEventListener) media.addEventListener('change', listener);
        else media.addListener(listener);
    }

    function installComposerControls() {
        const extensions = document.querySelector('#extensionsMenuButton');
        const options = document.querySelector('#options_button');
        if (extensions) extensions.classList.add('local-agent-hidden-control');
        if (options && !document.querySelector('#local-agent-tools-button')) {
            const tools = document.createElement('button');
            tools.type = 'button';
            tools.id = 'local-agent-tools-button';
            tools.className = 'local-agent-composer-button';
            tools.title = 'Tools';
            tools.setAttribute('aria-label', 'Tools');
            tools.textContent = '✦';
            tools.addEventListener('click', () => {
                const button = document.querySelector('#extensionsMenuButton');
                if (button) button.click();
            });
            options.parentElement.insertBefore(tools, options.nextSibling);
        }
        const send = document.querySelector('#send_but');
        if (send) {
            send.classList.remove('fa-solid', 'fa-paper-plane');
            send.classList.add('local-agent-send-button');
            if (send.textContent !== '➤') send.textContent = '➤';
            send.setAttribute('aria-label', 'Send message');
            send.title = 'Send message';
        }

        function installBranding() {
            document.querySelectorAll('.splash-logo, link[rel="icon"], link[rel="apple-touch-icon"]').forEach((element) => {
                if (element.tagName === 'LINK') {
                    element.href = '/img/n2llm-logo.png';
                } else if (element.src !== `${window.location.origin}/img/n2llm-logo.png`) {
                    element.src = '/img/n2llm-logo.png';
                }
            });
            document.title = 'N2LLM';
        }
    }

    function showPage(action) {
        const pages = ensurePages();
        pages.classList.toggle('open', action === 'profile' || action === 'settings');
        pages.querySelectorAll('.local-agent-page').forEach((page) => {
            page.classList.toggle('active', page.dataset.page === action);
        });
        document.body.classList.toggle('local-agent-page-active', action === 'profile' || action === 'settings');
    }

    function activate(action) {
        closePanels();
        showPage(action);
        if (action === 'settings') {
            document.body.classList.remove('local-agent-settings-open');
        } else if (action === 'profile') {
            document.body.classList.remove('local-agent-settings-open');
        } else if (action === 'files') {
            document.body.classList.remove('local-agent-settings-open');
            installFiles();
        } else {
            document.body.classList.remove('local-agent-settings-open');
            document.body.classList.remove('local-agent-page-active');
            window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
            const chat = document.querySelector('#chat');
            if (chat) chat.focus({ preventScroll: true });
        }
        document.querySelectorAll('.local-agent-tab').forEach((tab) => {
            tab.classList.toggle('active', tab.dataset.destination === action);
        });
    }

    function install() {
        if (document.querySelector('#local-agent-navigation')) return;
        const navigation = document.createElement('nav');
        navigation.id = 'local-agent-navigation';
        navigation.setAttribute('aria-label', 'Local Agent navigation');
        [
            ['chat', 'CHAT'],
            ['files', 'FILES'],
            ['profile', 'PROFILE'],
            ['settings', 'SETTINGS'],
        ].forEach(([destination, label]) => {
            const tab = document.createElement('button');
            tab.type = 'button';
            tab.className = 'local-agent-tab';
            tab.dataset.destination = destination;
            tab.textContent = label;
            tab.addEventListener('click', () => activate(destination));
            navigation.appendChild(tab);
        });
        document.body.appendChild(navigation);
        ensurePages();
        installComposerControls();
        installBranding();
        installWelcome();
        activate('chat');
    }

    async function installFiles() {
        let panel = document.querySelector('#local-agent-files');
        if (!panel) {
            panel = document.createElement('section');
            panel.id = 'local-agent-files';
            panel.innerHTML = '<div class="local-agent-files-header"><h2>N2LLM Files</h2><button type="button" id="local-agent-files-refresh">Refresh</button></div>' +
                '<p class="local-agent-files-status">Local indexed files and chat library files.</p><div class="local-agent-file-list"></div>';
            document.body.appendChild(panel);
            panel.querySelector('#local-agent-files-refresh').addEventListener('click', () => installFiles());
        }
        panel.classList.add('open');
        try {
            const response = await fetch('http://127.0.0.1:8090/files');
            if (!response.ok) throw new Error('file service unavailable');
            const data = await response.json();
            const list = panel.querySelector('.local-agent-file-list');
            list.replaceChildren(...(data.files || []).map((file) => {
                const card = document.createElement('article');
                card.className = 'local-agent-file-card';
                card.innerHTML = '<strong></strong><span></span><button type="button">Copy path</button>';
                card.querySelector('strong').textContent = file.filename;
                card.querySelector('span').textContent = (file.file_type || file.extension || 'file') +
                    ' • ' + (file.size_bytes || 0).toLocaleString() + ' bytes' +
                    (file.is_missing ? ' • unavailable' : '');
                card.querySelector('button').addEventListener('click', () =>
                    navigator.clipboard && navigator.clipboard.writeText(file.original_path || file.managed_path || ''));
                return card;
            }));
        } catch (error) {
            panel.querySelector('.local-agent-files-status').textContent = error.message;
        }
    }

    function installWelcome() {
        const welcome = document.querySelector('.welcomeHeaderTitle, .welcomeHeader');
        if (!welcome || document.querySelector('#local-agent-welcome')) return;
        const panel = document.createElement('div');
        panel.id = 'local-agent-welcome';
        panel.innerHTML = '<div class="local-agent-clippy" aria-hidden="true"><span></span></div>' +
            '<div><strong>Hej! Jeg er Local Agent.</strong><br><span>Hvad kan jeg hj\u00e6lpe dig med i dag?</span></div>';
        welcome.parentElement.insertBefore(panel, welcome);
    }

    function removeConnectionNotice(root) {
        const text = (root.textContent || '').toLowerCase();
        if (text.length > 500 || root.children.length > 6) return;
        if (!/(api|connection|forbindelse|connected|koblet)/.test(text)) return;
        if (/(not connected|disconnected|no api|ikke forbundet|ikke koblet|connect to an api)/.test(text)) {
            root.remove();
        }
    }

    function hideApiStatus() {
        document.querySelectorAll('#API-status-top, .online_status_text').forEach((element) => {
            element.setAttribute('aria-hidden', 'true');
            element.style.display = 'none';
        });
    }

    function removeDefaultWelcomeCard() {
        const markers = [
            "if you're connected to an api",
            'set any character as your welcome page assistant',
        ];
        document.querySelectorAll('.mes, .mes_text, .welcomeMessage, .welcome-assistant-message, .welcomeShortcuts, .welcomeButtons').forEach((element) => {
            if (element.id === 'local-agent-welcome') return;
            const text = (element.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
            if (markers.some((marker) => text.indexOf(marker) !== -1)) {
                const card = element.closest('.mes') || element.closest('.welcomeMessage') || element;
                if (card.id !== 'local-agent-welcome') card.remove();
            }
        });
        document.querySelectorAll('button, a, .menu_button').forEach((element) => {
            const text = (element.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
            if (!/(api connections|character management|extensions)/.test(text)) return;
            const group = element.closest('.welcomeShortcuts, .welcomeButtons');
            if (group) group.remove();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', install, { once: true });
    } else {
        install();
    }
    const observer = new MutationObserver((mutations) => {
        installWelcome();
        installComposerControls();
        installBranding();
        hideApiStatus();
        removeDefaultWelcomeCard();
        mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
            if (node.nodeType === Node.ELEMENT_NODE) removeConnectionNotice(node);
        }));
    });
    observer.observe(document.body, { childList: true, subtree: true });
    hideApiStatus();
    removeDefaultWelcomeCard();
    window.setInterval(removeDefaultWelcomeCard, 500);
})();
