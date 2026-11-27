document.addEventListener('DOMContentLoaded', function () {
    initConfirmForms();
    initPageLoader();
    initFlashAlerts();
    initDropzone('arquivo-excel', 'dropzone-excel', 'file-card-excel', 'file-name-excel', 'file-size-excel', 'btn-clear-excel');
    initDropzone('arquivo-pdf', 'dropzone-pdf', 'file-card-pdf', 'file-name-pdf', 'file-size-pdf', 'btn-clear-pdf');
    initTableFilters();
    initUploadSubmitFeedback();

    /**
     * Exibe dialogo de confirmacao de forma segura via atributo data-confirm,
     * evitando interpolacao de dados do servidor em handlers inline (XSS).
     */
    function initConfirmForms() {
        document.addEventListener('submit', function (e) {
            const form = e.target;
            if (!form || !form.dataset || !form.dataset.confirm) return;
            if (!window.confirm(form.dataset.confirm)) {
                e.preventDefault();
            }
        });
    }

    function safeSessionGet(chave) {
        try {
            return sessionStorage.getItem(chave);
        } catch (_err) {
            return null;
        }
    }

    function safeSessionSet(chave, valor) {
        try {
            sessionStorage.setItem(chave, valor);
        } catch (_err) {
            // Ignora indisponibilidade de sessionStorage
        }
    }

    function safeSessionRemove(chave) {
        try {
            sessionStorage.removeItem(chave);
        } catch (_err) {
            // Ignora indisponibilidade de sessionStorage
        }
    }

    /**
     * Controla o overlay de carregamento durante navegacao entre paginas,
     * envio de formularios e atualizacoes dinamicas via API.
     */
    function initPageLoader() {
        const overlay = document.getElementById('page-loader');
        if (!overlay) return;

        let hideTimer = null;

        function show() {
            clearTimeout(hideTimer);
            overlay.hidden = false;
            overlay.setAttribute('aria-busy', 'true');
            overlay.classList.add('visible');
        }

        function hide(suave) {
            clearTimeout(hideTimer);
            safeSessionRemove('ete_nav_loading');
            overlay.classList.remove('visible');
            overlay.setAttribute('aria-busy', 'false');
            if (suave) {
                hideTimer = setTimeout(() => {
                    overlay.hidden = true;
                }, 200);
            } else {
                overlay.hidden = true;
            }
        }

        window.EteLoader = { show, hide };

        if (safeSessionGet('ete_nav_loading') === '1') {
            hideTimer = setTimeout(() => hide(true), 220);
        }

        document.addEventListener('click', function (e) {
            if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
                return;
            }
            const link = e.target.closest('a[href]');
            if (!link) return;
            const href = link.getAttribute('href') || '';
            if (
                !href ||
                href.startsWith('#') ||
                href.startsWith('javascript:') ||
                link.hasAttribute('download') ||
                link.target === '_blank' ||
                href.endsWith('/pdf')
            ) {
                return;
            }
            try {
                const url = new URL(link.href, window.location.origin);
                if (url.origin !== window.location.origin) return;
                if (url.pathname === window.location.pathname && url.search === window.location.search) return;
            } catch (_err) {
                return;
            }
            safeSessionSet('ete_nav_loading', '1');
            show();
        });

        document.addEventListener('submit', function (e) {
            if (e.defaultPrevented) return;
            safeSessionSet('ete_nav_loading', '1');
            show();
        });

        window.addEventListener('pageshow', function (e) {
            if (e.persisted || safeSessionGet('ete_nav_loading') === '1') {
                hide(false);
            }
        });
    }

    /**
     * Configura uma area de upload com suporte a drag-and-drop, pre-visualizacao
     * de nome e tamanho do arquivo e preservacao do arquivo caso o seletor seja cancelado.
     */
    function initDropzone(inputId, dropzoneId, cardId, nameId, sizeId, clearBtnId) {
        const input = document.getElementById(inputId);
        const dropzone = document.getElementById(dropzoneId);
        const card = document.getElementById(cardId);
        const nameEl = document.getElementById(nameId);
        const sizeEl = document.getElementById(sizeId);
        const clearBtn = document.getElementById(clearBtnId);

        if (!input || !dropzone) return;

        let ultimoArquivoValido = null;

        ['dragenter', 'dragover'].forEach(eventName => {
            dropzone.addEventListener(eventName, function (e) {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add('drag-active');
            }, false);
        });

        dropzone.addEventListener('dragleave', function (e) {
            e.preventDefault();
            e.stopPropagation();
            if (!e.relatedTarget || !dropzone.contains(e.relatedTarget)) {
                dropzone.classList.remove('drag-active');
            }
        }, false);

        dropzone.addEventListener('drop', function (e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('drag-active');
            const files = e.dataTransfer ? e.dataTransfer.files : null;
            if (files && files.length > 0) {
                ultimoArquivoValido = files[0];
                if (typeof DataTransfer !== 'undefined') {
                    const dt = new DataTransfer();
                    dt.items.add(files[0]);
                    input.files = dt.files;
                } else {
                    input.files = files;
                }
                updateFileDisplay(files[0]);
            }
        }, false);

        input.addEventListener('change', function () {
            if (this.files && this.files.length > 0) {
                ultimoArquivoValido = this.files[0];
                updateFileDisplay(this.files[0]);
            } else if (ultimoArquivoValido && typeof DataTransfer !== 'undefined') {
                const dt = new DataTransfer();
                dt.items.add(ultimoArquivoValido);
                this.files = dt.files;
                updateFileDisplay(ultimoArquivoValido);
            } else {
                clearFile();
            }
        });

        if (clearBtn) {
            clearBtn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                input.click();
            });
        }

        function updateFileDisplay(file) {
            if (card && nameEl) {
                nameEl.textContent = file.name;
                if (sizeEl) {
                    const sizeInKB = (file.size / 1024).toFixed(1);
                    const sizeInMB = (file.size / (1024 * 1024)).toFixed(2);
                    sizeEl.textContent = file.size > 1024 * 1024 ? `${sizeInMB} MB` : `${sizeInKB} KB`;
                }
                card.classList.add('visible');
            }
        }

        function clearFile() {
            ultimoArquivoValido = null;
            input.value = '';
            if (card) {
                card.classList.remove('visible');
            }
        }
    }

    /**
     * Inicializa busca rapida nas tabelas que possuem o atributo data-table-filter.
     */
    function initTableFilters() {
        document.querySelectorAll('[data-table-filter]').forEach(function (input) {
            const targetId = input.getAttribute('data-table-filter');
            const table = document.getElementById(targetId);
            if (!table) return;

            input.addEventListener('input', function () {
                const termo = input.value.trim().toLowerCase();
                table.querySelectorAll('tbody tr[data-searchable="true"]').forEach(function (tr) {
                    const ocultoPorCampanha = tr.dataset.campanhaHidden === 'true';
                    const visivel = !ocultoPorCampanha && (!termo || (tr.textContent || '').toLowerCase().includes(termo));
                    tr.style.display = visivel ? '' : 'none';
                    const next = tr.nextElementSibling;
                    if (next && next.hasAttribute('data-detail-row')) {
                        next.style.display = visivel ? '' : 'none';
                    }
                });
            });
        });
    }

    /**
     * Permite fechar alertas flash (com remocao suave) e alertas inline via data-dismiss-target.
     */
    function initFlashAlerts() {
        document.querySelectorAll('[data-flash-dismiss]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const alerta = btn.closest('[data-flash-alert]');
                if (!alerta) return;
                alerta.style.opacity = '0';
                alerta.style.transform = 'translateY(-4px)';
                setTimeout(function () {
                    alerta.remove();
                }, 180);
            });
        });

        document.querySelectorAll('[data-dismiss-target]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const alvo = document.getElementById(btn.dataset.dismissTarget);
                if (alvo) alvo.classList.add('hidden');
            });
        });
    }

    /**
     * Desabilita o botao de envio e exibe indicador de processamento para evitar cliques duplicados.
     * Reabilita automaticamente ao voltar pelo historico do navegador (bfcache).
     */
    function initUploadSubmitFeedback() {
        const forms = document.querySelectorAll('form[data-upload-form]');
        forms.forEach(function (form) {
            const btn = form.querySelector('button[type="submit"]');
            const label = btn ? btn.querySelector('[data-submit-label]') : null;
            if (label && !label.dataset.originalLabel) {
                label.dataset.originalLabel = label.textContent;
            }
            form.addEventListener('submit', function (e) {
                if (e.defaultPrevented || !btn) return;
                btn.disabled = true;
                btn.classList.add('opacity-70', 'cursor-not-allowed');
                if (label) {
                    label.textContent = form.dataset.loadingText || 'Processando...';
                }
            });
        });

        window.addEventListener('pageshow', function () {
            forms.forEach(function (form) {
                const btn = form.querySelector('button[type="submit"]');
                if (!btn) return;
                btn.disabled = false;
                btn.classList.remove('opacity-70', 'cursor-not-allowed');
                const label = btn.querySelector('[data-submit-label]');
                if (label && label.dataset.originalLabel) {
                    label.textContent = label.dataset.originalLabel;
                }
            });
        });
    }
});
