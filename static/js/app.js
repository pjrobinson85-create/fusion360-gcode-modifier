document.addEventListener('DOMContentLoaded', () => {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const browseBtn = document.getElementById('browse-btn');
    const uploadPhase = document.getElementById('upload-phase');
    const fileListPhase = document.getElementById('file-list-phase');
    const successPhase = document.getElementById('success-phase');
    const uploadStatus = document.getElementById('upload-status');
    const fileListEl = document.getElementById('file-list');
    const stitchBtn = document.getElementById('stitch-btn');
    const cancelStitchBtn = document.getElementById('cancel-stitch-btn');
    const downloadBtn = document.getElementById('download-btn');
    const resetBtn = document.getElementById('reset-btn');
    const notificationArea = document.getElementById('notification-area');

    let selectedFiles = []; // Array to hold the files for sorting

    // --- Drag and Drop Logic --- //

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => {
            dropZone.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => {
            dropZone.classList.remove('dragover');
        }, false);
    });

    dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles(files);
    });

    // --- Browse Button Logic --- //
    browseBtn.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', function () {
        handleFiles(this.files);
    });

    // --- Upload and Process --- //
    function handleFiles(files) {
        if (files.length === 0) return;

        let validFiles = [];
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            if (file.name.endsWith('.nc') || file.name.endsWith('.tap')) {
                validFiles.push(file);
            } else {
                showNotification(`Skipped ${file.name}: Invalid file type.`, 'error');
            }
        }

        if (validFiles.length > 0) {
            selectedFiles = validFiles;
            renderFileList();

            uploadPhase.classList.add('hidden');
            fileListPhase.classList.remove('hidden');
        }
    }

    // Render the list of files to be stitched
    function renderFileList() {
        fileListEl.innerHTML = '';
        selectedFiles.forEach((file, index) => {
            const li = document.createElement('li');
            li.draggable = true;
            li.dataset.index = index;
            li.innerHTML = `
                <i class="fa-solid fa-grip-vertical drag-handle"></i>
                <span class="file-name">${file.name}</span>
                <span class="file-size">${(file.size / 1024).toFixed(1)} KB</span>
            `;

            // Drag and drop rendering within the list
            li.addEventListener('dragstart', handleDragStart);
            li.addEventListener('dragover', handleDragOverList);
            li.addEventListener('drop', handleDropList);
            li.addEventListener('dragenter', handleDragEnterList);
            li.addEventListener('dragleave', handleDragLeaveList);

            fileListEl.appendChild(li);
        });
    }

    let draggedItemIndex = null;

    function handleDragStart(e) {
        draggedItemIndex = parseInt(this.dataset.index);
        e.dataTransfer.effectAllowed = 'move';
        this.classList.add('dragging');
    }

    function handleDragOverList(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        return false;
    }

    function handleDragEnterList(e) {
        this.classList.add('over');
    }

    function handleDragLeaveList(e) {
        this.classList.remove('over');
    }

    function handleDropList(e) {
        e.stopPropagation();
        this.classList.remove('over');

        const targetIndex = parseInt(this.dataset.index);
        if (draggedItemIndex !== targetIndex && draggedItemIndex !== null) {
            // Swap in array
            const draggedItem = selectedFiles[draggedItemIndex];
            selectedFiles.splice(draggedItemIndex, 1);
            selectedFiles.splice(targetIndex, 0, draggedItem);
            renderFileList();
        }
        return false;
    }

    cancelStitchBtn.addEventListener('click', () => {
        selectedFiles = [];
        fileListPhase.classList.add('hidden');
        uploadPhase.classList.remove('hidden');
    });

    stitchBtn.addEventListener('click', () => {
        uploadFiles(selectedFiles);
    });

    function uploadFiles(files) {
        // UI State: Show Loading
        fileListPhase.classList.add('hidden');
        uploadPhase.classList.remove('hidden');
        dropZone.classList.add('hidden');
        uploadStatus.classList.remove('hidden');

        const formData = new FormData();
        files.forEach(file => {
            formData.append('files[]', file);
        });

        fetch('/api/stitch', {
            method: 'POST',
            body: formData
        })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => { throw new Error(err.error || 'Upload failed'); });
                }
                return response.json();
            })
            .then(data => {
                // UI State: Show Success
                uploadStatus.classList.add('hidden');
                uploadPhase.classList.add('hidden');
                successPhase.classList.remove('hidden');

                // Set download link
                downloadBtn.href = data.download_url;
                downloadBtn.download = data.filename;
            })
            .catch(error => {
                // UI State: Reset to upload
                uploadStatus.classList.add('hidden');
                dropZone.classList.remove('hidden');
                showNotification(error.message, 'error');
            });
    }

    // --- Reset Flow --- //
    resetBtn.addEventListener('click', () => {
        successPhase.classList.add('hidden');
        uploadPhase.classList.remove('hidden');
        dropZone.classList.remove('hidden');
        uploadStatus.classList.add('hidden');
        fileInput.value = ''; // clear input
    });

    // --- Notifications --- //
    function showNotification(message, type) {
        const notif = document.createElement('div');
        notif.className = `notification ${type}`;

        const icon = document.createElement('i');
        icon.className = 'fa-solid fa-circle-exclamation';

        const msg = document.createElement('span');
        msg.textContent = message;

        notif.appendChild(icon);
        notif.appendChild(msg);
        notificationArea.appendChild(notif);

        // Auto remove
        setTimeout(() => {
            notif.style.animation = 'slideIn 0.3s ease-in reverse forwards';
            setTimeout(() => notif.remove(), 300);
        }, 5000);
    }
});
