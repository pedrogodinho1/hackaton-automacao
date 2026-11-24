document.addEventListener('DOMContentLoaded', function () {
    initDropzone('arquivo-excel', 'dropzone-excel', 'file-card-excel', 'file-name-excel', 'file-size-excel', 'btn-clear-excel');
    initDropzone('arquivo-pdf', 'dropzone-pdf', 'file-card-pdf', 'file-name-pdf', 'file-size-pdf', 'btn-clear-pdf');
    initTableFilters();
    initUploadSubmitFeedback();

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

        ['dragleave', 'drop'].forEach(eventName => {
            dropzone.addEventListener(eventName, function (e) {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove('drag-active');
            }, false);
        });

        dropzone.addEventListener('drop', function (e) {
            const files = e.dataTransfer.files;
            if (files && files.length > 0) {
                ultimoArquivoValido = files[0];
                input.files = files;
                updateFileDisplay(files[0]);
            }
        });

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
     * Desabilita o botao de envio e exibe indicador de processamento para evitar cliques duplicados.
     */
    function initUploadSubmitFeedback() {
        document.querySelectorAll('form[data-upload-form]').forEach(function (form) {
            form.addEventListener('submit', function () {
                const btn = form.querySelector('button[type="submit"]');
                if (!btn) return;
                btn.disabled = true;
                btn.classList.add('opacity-70', 'cursor-not-allowed');
                const label = btn.querySelector('[data-submit-label]');
                if (label) {
                    label.textContent = form.dataset.loadingText || 'Processando...';
                }
            });
        });
    }
});
