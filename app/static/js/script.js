let taskId = null;

document.addEventListener('DOMContentLoaded', function() {
    const processForm = document.getElementById('processForm');
    const processBtn = document.getElementById('processBtn');
    const progressSection = document.getElementById('progressSection');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const currentStep = document.getElementById('currentStep');
    const resultSection = document.getElementById('resultSection');
    const audioPlayer = document.getElementById('audioPlayer');
    const downloadLink = document.getElementById('downloadLink');
    const newProcessBtn = document.getElementById('newProcessBtn');

    processForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const inputUrl = document.getElementById('inputUrl').value;
        
        // Disable button and show loading state
        processBtn.disabled = true;
        processBtn.textContent = 'Processing...';
        
        try {
            // Send processing request
            const response = await fetch('/process', {
                method: 'POST',
                body: new FormData(processForm)
            });
            
            const data = await response.json();
            
            if (data.task_id) {
                taskId = data.task_id;
                
                // Hide form, show progress bar
                processForm.style.display = 'none';
                progressSection.style.display = 'block';
                
                // Start polling progress
                pollProgress();
            } else {
                throw new Error('Failed to get task ID');
            }
        } catch (error) {
            alert('Processing request failed: ' + error.message);
            resetForm();
        }
    });
newProcessBtn.addEventListener('click', function() {
    // Reset interface
    resetForm();
    
    // Show input form
    processForm.style.display = 'block';
    progressSection.style.display = 'none';
    resultSection.style.display = 'none';
});

async function pollProgress() {
    if (!taskId) return;
    
    try {
        const response = await fetch(`/status/${taskId}`);
        const status = await response.json();
        
        if (status.error) {
            throw new Error(status.error);
        }
        
        // Update progress bar
        progressFill.style.width = `${status.progress}%`;
        progressText.textContent = `${status.progress}%`;
        currentStep.textContent = status.message;
        
        if (status.step === 'completed' && status.result) {
            // Processing completed, show result
            showResult(status.result);
        } else if (status.step === 'error') {
            // Processing error
            throw new Error(status.message);
        } else {
            // Continue polling
            setTimeout(pollProgress, 1000);
        }
    } catch (error) {
        alert('Failed to get progress: ' + error.message);
        resetForm();
    }
}

function showResult(audioPath) {
    // Hide progress bar, show result
    progressSection.style.display = 'none';
    resultSection.style.display = 'block';
    
    // Set up audio player
    audioPlayer.src = `/download/${taskId}`;
    
    // Set up download link
    downloadLink.href = `/download/${taskId}`;
    downloadLink.download = `translated_audio_${taskId}.wav`;
}

function resetForm() {
    // Reset button state
    processBtn.disabled = false;
    processBtn.textContent = 'Start Processing';
    
    // Clear input
    document.getElementById('inputUrl').value = '';
    
    // Reset progress bar
    progressFill.style.width = '0%';
    progressText.textContent = 'Ready to start...';
    currentStep.textContent = '';
    
    // Stop audio playback
    audioPlayer.pause();
    audioPlayer.src = '';
    
    taskId = null;
}

});