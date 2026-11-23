document.addEventListener('DOMContentLoaded', function () {
    initDropzone('arquivo-excel', 'dropzone-excel', 'file-card-excel', 'file-name-excel', 'file-size-excel', 'btn-clear-excel');
    initDropzone('arquivo-pdf', 'dropzone-pdf', 'file-card-pdf', 'file-name-pdf', 'file-size-pdf', 'btn-clear-pdf');

    /**
     * Configura uma area de upload com suporte a drag-and-drop, pre-visualizacao
     * de nome e tamanho do arquivo e reabertura do seletor pelo botao de troca.
     */
    function initDropzone(inputId, dropzoneId, cardId, nameId, sizeId, clearBtnId) {
        const input = document.getElementById(inputId);
        const dropzone = document.getElementById(dropzoneId);
        const card = document.getElementById(cardId);
        const nameEl = document.getElementById(nameId);
        const sizeEl = document.getElementById(sizeId);
        const clearBtn = document.getElementById(clearBtnId);

        if (!input || !dropzone) return;

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
                input.files = files;
                updateFileDisplay(files[0]);
            }
        });

        input.addEventListener('change', function () {
            if (this.files && this.files.length > 0) {
                updateFileDisplay(this.files[0]);
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
            input.value = '';
            if (card) {
                card.classList.remove('visible');
            }
        }
    }
});
