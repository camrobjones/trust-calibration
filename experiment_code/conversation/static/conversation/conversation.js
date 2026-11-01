Vue.config.delimiters = ["[[", "]]"];

const roleMap = {
    "T": "Decider",
    "P": "Advisor"
}


function showToast(title, message, buttonText, buttonFunction=hideToast) {
    var toast = document.getElementById("toast");
    var toastTitle = document.getElementById("toast-title");
    var toastMessage = document.getElementById("toast-message");
    var toastButton = document.getElementById("toast-button");

    toastTitle.innerHTML = title;
    toastMessage.innerHTML = message;
    toastButton.innerHTML = buttonText;
    toastButton.onclick = buttonFunction;

    toast.style.display = "flex";
}

function hideToast() {
    var toast = document.getElementById("toast");
    toast.style.display = "none";
}




var app = new Vue({
    el: '#app',
    delimiters: ['[[', ']]'],
    mounted: function() {

        // consle.log("mounted");
        this.parsePageData();
        this.initWebSocket();
        this.startTimer();

        // Chat container height
        this.setChatContainerHeight();
        window.addEventListener('resize', this.setChatContainerHeight);

        // on focus
        this.$refs.messageInput.addEventListener('focus', () => {
            setTimeout(this.setChatContainerHeight, 200);
            document.body.style.overflow = 'hidden';
        });

        // on blur
        this.$refs.messageInput.addEventListener('blur', () => {
            setTimeout(this.setChatContainerHeight, 200);
            document.body.style.overflow = 'auto';
        });
        
    },
    beforeDestroy() {
        clearInterval(this.timer);
        window.removeEventListener('resize', this.setChatContainerHeight);
        if (this.socket) {
            this.socket.close();
        }
        window.removeEventListener('beforeunload', this.beforeUnloadHandler);
    },
    data: {
        // General
        socket: null,
        messages: [],
        gameOver: false,
        role: "",
        role_hr: "",
        feedbackCondition: "",
        hintCondition: 0,
        input: "",
        typing: false,
        typingTimeout: null,
        overlay: "help",
        chatPopoverMessage: "",

        question: "",
        answer1: "",
        answer2: "",
        randomizeAnswers: Math.random() < 0.5,
        persuaderAnswer: "",

        verdict: null,
        confidence: 50,
        reason: "",
        verdict_submitted: false,
        verdictError: null,
        ConfidenceAdjusted: false,

        isCorrect: null,
        correctAnswer: null,
        targetAnswer: null,

        timeRemaining: 5 * 60, // In seconds
        timer: null,
        reconnectAttempts: 0,
        reconnectTimer: null,
        inactivityTimer: null,
        inactivityWarningTimer: null,
        skipBeforeUnload: false,
    },
    computed: {
        // Other computed properties...
        formattedTimeRemaining() {
            let minutes = Math.floor(this.timeRemaining / 60);
            let seconds = this.timeRemaining % 60;
            return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        },

        lastMsgUser() {
            if (this.messages.length < 1) {
                return false;
            }
            return this.messages[this.messages.length - 1].role === this.role;
        },

        canSendMessage() {
        return this.input !== '' && 
            !(this.gameOver) &&
            !(this.messages.length > 0 && this.messages[this.messages.length - 1].role === this.role);
        },

        canSubmitVerdict() {
            // In hint condition, always allow submitting verdict
            if (this.hintCondition === 1) {
                return true;
            }
            // In interactive condition, require at least 3 messages
            return this.messages.length > 3 || this.gameOver;
        },

        verdictValid() {
            return this.verdict !== null && this.ConfidenceAdjusted && this.reason.length > 0 && this.canSubmitVerdict;
        }
    },
    methods: {

        parsePageData: function() {
            // Get the role from the template
            context = JSON.parse(document.getElementById('context').textContent);
            console.log(context);
            this.pptId = context.ppt_id;
            this.role = context.role;
            this.feedbackCondition = context.feedback_cond;
            this.hintCondition = context.hint_cond;
            this.role_hr = roleMap[this.role];
            this.conversation = context.conversation;
            this.question = context.question.question;
            this.answer1 = context.question.answer1;
            this.answer2 = context.question.answer2;
            this.timeRemaining = this.conversation.time_remaining;
            
            // Get the persuader's answer (what the LLM would argue for)
            const persuaderAnswerKey = this.conversation.persuader_answer;
            if (persuaderAnswerKey === "answer1") {
                this.persuaderAnswer = this.answer1;
            } else {
                this.persuaderAnswer = this.answer2;
            }
            
            // Also set correctAnswer for feedback
            const correctAnswerKey = this.conversation.correct_answer;
            if (correctAnswerKey === "answer1") {
                this.correctAnswer = this.answer1;
            } else {
                this.correctAnswer = this.answer2;
            }

            if (this.timeRemaining < 1) {
                this.endGame();
            }

            //update progress bar
            let pb = document.getElementById('jspsych-progressbar-inner')
            pb.style.width = (this.conversation.trial_index * 20) + "%";
            
            // update Messages
            for (let i=0; i < this.conversation.messages.length; i++) {
                let data = this.conversation.messages[i];
                this.pushMessage(data);
            }

            // Add leave-page warning to reduce accidental tab closes
            window.addEventListener('beforeunload', this.beforeUnloadHandler);
            // Start inactivity timers for AFK UX
            this.resetInactivityTimers();
        },

        startTimer: function() {
            clearInterval(this.timer)
            this.timer = setInterval(() => {
                if (this.timeRemaining > 0) {
                    this.timeRemaining--;
                } else {
                    if (this.gameOver == false) {
                        this.endGame();
                    }
                    clearInterval(this.timer);
                }
            }, 1000);
        },

        // handleMessage: function (e) {
        //     let data = JSON.parse(e.data);
        //     // console.log(data)

        //     if (data.type == "game_data") {
        //         this.messages = data.messages;
        //         this.timeRemaining = data.timeRemaining;
        //         this.startTimer();
        //         if (this.messages.length > 0 && this.overlay == "help") {
        //             this.closeOverlay();
        //         }
        //         return;
        //     }
        // },

        updateChatUI() {
            this.$nextTick(() => {
                let chatLog = document.querySelector('#chat-log');
                chatLog.scrollTop = chatLog.scrollHeight;
                // chatLog.lastElementChild.scrollIntoView({behavior:"smooth", block: "end"});
            });

            this.$refs.messageInput.focus();  // Focus keyboard
            this.$refs.messageInput.style.height = 'auto';  // reset height
        },

        pushMessage(data) {
            let message = data.message;
            let sentByMe = data.role === this.role;
            let first = this.messages.filter(m => m.role === data.role).length === 0;
            let label = sentByMe ? 'You' : roleMap[data.role];

            let messageObj = {
                'message': message,
                'role': data.role,
                'sentByMe': sentByMe,
                'first': first,
                'label': label
            };

            this.messages.push(messageObj);
            this.updateChatUI();
        },

        async fetchMessagesFromServer() {
            try {
                const response = await fetch(`/conversation/get_messages/?conv_id=${this.conversation.id}`);
                if (!response.ok) {
                    this.skipBeforeUnload = true;
                    window.location.reload();
                    return;
                }
                const data = await response.json();
                
                if (data.messages) {
                    // Clear current messages and rebuild from server data
                    this.messages = [];
                    
                    for (let msgData of data.messages) {
                        let sentByMe = msgData.role === this.role;
                        let first = this.messages.filter(m => m.role === msgData.role).length === 0;
                        let label = sentByMe ? 'You' : roleMap[msgData.role];

                        this.messages.push({
                            'message': msgData.message,
                            'role': msgData.role,
                            'sentByMe': sentByMe,
                            'first': first,
                            'label': label
                        });
                    }
                    
                    this.updateChatUI();
                }
            } catch (error) {
                console.error('Failed to fetch messages:', error);
                this.skipBeforeUnload = true;
                window.location.reload();
            }
        },

        beforeUnloadHandler(event) {
            if (this.skipBeforeUnload || this.gameOver) {
                return;
            }
            event.preventDefault();
            event.returnValue = '';
        },

        initWebSocket() {
            const scheme = window.location.protocol === "https:" ? "wss" : "ws";
            const socketUrl = `${scheme}://${window.location.host}/ws/conversation/${this.conversation.id}/`;

            this.socket = new WebSocket(socketUrl);

            this.socket.onopen = () => {
                console.log("WebSocket connected");
                // Reset reconnect attempts and timers
                this.clearReconnect();
                this.reconnectAttempts = 0;
                // Resync messages on reconnect/open
                this.fetchMessagesFromServer();
            };

            this.socket.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === "chat.message") {
                    // Instead of adding individual messages, fetch fresh message history from server
                    this.fetchMessagesFromServer();
                    this.typing = false;
                    this.resetInactivityTimers();
                } else if (data.type === "conversation.ended") {
                    // AFK or timeout end: navigate to exit survey
                    this.skipBeforeUnload = true;
                    this.overlay = 'afk_ended';
                    setTimeout(() => {
                        window.location.href = `/conversation/exit_survey/${this.pptId}/`;
                    }, 5000);
                } else if (data.type === "decision.made") {
                    // Show decision made overlay for Persuader
                    if (this.role === "P") {
                        this.gameOver = true;
                        this.overlay = "decision_made";
                    }
                }
            };

            this.socket.onerror = () => {
                // Force a simple, robust reconnect path: reload the page
                const reloadNow = () => { this.skipBeforeUnload = true; window.location.reload(); };
                showToast("Connection issue", "We hit a server error. Reloading to reconnect...", "Reload now", reloadNow);
                setTimeout(reloadNow, 5000);
            };

            this.socket.onclose = () => {
                const reloadNow = () => { this.skipBeforeUnload = true; window.location.reload(); };
                if (!navigator.onLine) {
                    showToast("Disconnected", "You appear to be offline. We'll reload when you're back online.", "Reload now", reloadNow);
                    window.addEventListener('online', reloadNow, { once: true });
                    return;
                }
                showToast("Disconnected", "Lost connection to server. Reloading to reconnect...", "Reload now", reloadNow);
                setTimeout(reloadNow, 5000);
            };
        },

        scheduleReconnect() {
            if (this.reconnectTimer) return;
            const base = 1000; // 1s
            const maxDelay = 30000; // 30s
            const delay = Math.min(maxDelay, base * Math.pow(2, this.reconnectAttempts || 0));
            this.reconnectAttempts = (this.reconnectAttempts || 0) + 1;

            this.reconnectTimer = setTimeout(() => {
                this.reconnectTimer = null;
                this.initWebSocket();
            }, delay);
        },

        clearReconnect() {
            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
                this.reconnectTimer = null;
            }
        },

        sendMessageToServer(data) {
            if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                const payload = {
                    action: "chat",
                    role: this.role,
                    message: data.message,
                };
                this.socket.send(JSON.stringify(payload));
            } else {
                showToast("Connection Error", "WebSocket is not connected.", "OK", hideToast);
            }
        },

        updateMessages(data) {
            this.messages = data.messages;
            this.timeRemaining = data.timeRemaining;

            this.updateChatUI();
        },

        setChatContainerHeight() {
            const navbarHeight = document.getElementById('navbar').offsetHeight;
            document.getElementById('chat-container').style.height = window.innerHeight - navbarHeight + 'px';
            
            // rescroll
            setTimeout(function(){
                window.scrollTo(0, 0, {behavior: 'smooth'});
                let chatLog = document.querySelector('#chat-log');
                chatLog.scrollTop = chatLog.scrollHeight;}, 100);
        },

        checkCanSendMessage() {
            if (this.gameOver) {
                this.openChatPopover("The game is over.")
                return false;
            }
            
            // Prevent persuader from messaging first
            if (this.role === 'P' && this.messages.length === 0) {
                this.openChatPopover("Wait for your partner to send a message first.")
                return false;
            }
            
            // General rule: can't send consecutive messages
            if ((this.role === 'W' && this.messages.length === 0) || (this.messages.length > 0 && this.messages[this.messages.length - 1].role === this.role)) {
                this.openChatPopover("Wait for the other player to respond.")
                return false;
            }
            if (!(this.input.length > 0)) {
                this.openChatPopover("You can't send an empty message!")
                return false;
            }

            return true;
        },

        sendMessage: function() {
            if (!this.checkCanSendMessage()) {
                return;
            }

            // Generate temporary ID for deduplication
            const tempId = Date.now() + '_' + Math.random().toString(36).substr(2, 9);

            const messageData = {
                message: this.input,
                temp_id: tempId
            };

            this.sendMessageToServer(messageData)

            // Add message immediately with temp ID
            this.pushMessage({message: this.input, role: this.role, temp_id: tempId})
            this.input = '';

            let lastMsg = app.messages.at(-1).message.length
            let readDelay = 40 * lastMsg

            this.typingTimeout = setTimeout(function() {
                app.typing = true;
                app.updateChatUI();
            }, readDelay + 1500 + Math.random() * 2000)
            this.resetInactivityTimers();
        },

        // AFK UX
        resetInactivityTimers() {
            if (this.inactivityWarningTimer) clearTimeout(this.inactivityWarningTimer);
            if (this.inactivityTimer) clearTimeout(this.inactivityTimer);
            // show a gentle warning at 2 min if it's our turn
            this.inactivityWarningTimer = setTimeout(() => {
                const noMessagesAndTarget = this.messages.length === 0 && this.role === 'T';
                const myTurn = this.messages.length > 0 && this.messages[this.messages.length - 1].role !== this.role;
                if ((noMessagesAndTarget || myTurn) && !this.gameOver) {
                    this.openChatPopover("It’s been 2 minutes—please respond within the next minute to avoid ending the session.", 60000);
                }
            }, 120000);
            // server enforces AFK at 180s
        },

        resizeTextArea: function() {
            this.$refs.messageInput.style.height = 'auto';
            this.$refs.messageInput.style.height = (this.$refs.messageInput.scrollHeight) + 'px';
            this.$refs.messageInput.scrollTop = this.$refs.messageInput.scrollHeight;
        },

        openOverlay: function(overlay) {
            this.overlay = overlay;
        },

        closeOverlay: function() {
            this.overlay = null;
        },

        toggleOverlay: function(overlay) {
            if (this.overlay == overlay) {
                this.closeOverlay();
            } else {
                this.overlay = overlay;
            }
        },

        messageInput: function(e) {
            if (this.input.length > 300) {
                let allowedKeys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Backspace", "Enter", "Tab", "Shift", "MetaLeft"]
                if (!(allowedKeys.includes(e.code))) {
                    e.preventDefault();
                    this.openChatPopover("Your message can't be longer than 300 characters.")
                }
            }
        },

        openChatPopover: function(message, timeout=5000) {
            this.chatPopoverMessage = message;
            let inputContainer = this.$refs.chatInputContainer;
            this.$refs.chatPopover.style.top = (inputContainer.offsetTop - 10) + "px";
            setTimeout(() => {
                app.chatPopoverMessage = "";
            }, timeout);
        },

        markConfidenceAdjusted() {
            this.ConfidenceAdjusted = true;
        },

        selectVerdict(verdict) {
            this.verdict = verdict;
            this.verdictError = null;
        },

        sendVerdictToServer(data) {
            // POST user data to server
            let url = `/conversation/send_verdict/`;
            let csrftoken = Cookies.get('csrftoken');
            let headers = { "X-CSRFToken": csrftoken };
            data.ppt_id = this.pptId;
            data.conversation_id = this.conversation.id;
            axios.post(url, data, { headers: headers })
                .then(response => {
                    console.log(response)
                    let data = response.data;
                    this.isCorrect = data.feedback.is_correct;
                    this.correctAnswer = data.feedback.correct_answer;
                    this.targetAnswer = data.feedback.target_answer;
                    this.verdict_submitted = true;
                    // Refresh the page
                    this.overlay = "feedback";
                    }
                )
                .catch(error => {
                    console.log(error.response.data);
                    this.verdict_submitted = false;
                });
        },

        nextConversation: function() {
            // refresh page
            window.location.reload();
        },

        submitVerdict: function(event) {

            // Verdict invalid
            if (this.verdict === null) {
                this.verdictError = "Please select a verdict";
                return;
            }

            // No confidence change
            if (!this.ConfidenceAdjusted) {
                this.verdictError = "Please adjust the confidence level";
                return;
            }

            // No reason
            if (this.reason.length < 1) {
                this.verdictError = "Please enter a reason";
                return;
            }

            if (!this.canSubmitVerdict) {
                this.verdictError = "Please interact more with the advisor.";
                return;
            }
 
            // Verdict already submitted
            // Allow multiple submissions because of the bug
            // if (this.verdict_submitted) {
            //     return;
            // }

            // Touch is already being handled, ignore click event
            if (event.type === 'click' && this.touchHandled) {
                this.touchHandled = false; // Reset the flag for next time
                return;
            }

            // If this was a touch event, set touchHandled to true
            if (event.type === 'touchstart') {
                this.touchHandled = true;
            }

            const messageData = {
                'type': 'verdict',
                'role': this.role,
                'verdict': this.verdict,
                'confidence': this.confidence,
                'reason': this.reason
            };
            console.log(messageData);

            this.sendVerdictToServer(messageData)

            this.gameOver = true;
            // this.openDemographics();
        },

        endGame: function() {
            this.gameOver = true;
            if (this.role == "P") {
                // Show waiting overlay for Persuader
                this.openOverlay("waiting");
            } else if (this.role == "T") {
                if (!this.verdict_submitted) {
                    this.openOverlay("decide");
                }
            }
        },
    }
});