// Telegram WebApp SDK Integration Bridge
window.TelegramBridge = {
  isAvailable: false,
  tg: null,
  userId: "web_guest",
  userName: "Гость",

  init() {
    if (window.Telegram && window.Telegram.WebApp) {
      this.tg = window.Telegram.WebApp;
      this.isAvailable = true;
      try {
        this.tg.ready();
        this.tg.expand();
        
        // Setup colors from Telegram theme
        if (this.tg.themeParams) {
          const root = document.documentElement;
          const tp = this.tg.themeParams;
          if (tp.bg_color) root.style.setProperty('--tg-theme-bg-color', tp.bg_color);
          if (tp.secondary_bg_color) root.style.setProperty('--tg-theme-secondary-bg-color', tp.secondary_bg_color);
          if (tp.text_color) root.style.setProperty('--tg-theme-text-color', tp.text_color);
          if (tp.hint_color) root.style.setProperty('--tg-theme-hint-color', tp.hint_color);
          if (tp.button_color) root.style.setProperty('--tg-theme-button-color', tp.button_color);
          if (tp.button_text_color) root.style.setProperty('--tg-theme-button-text-color', tp.button_text_color);
        }

        // Extract user data
        if (this.tg.initDataUnsafe && this.tg.initDataUnsafe.user) {
          const u = this.tg.initDataUnsafe.user;
          this.userId = String(u.id);
          this.userName = u.first_name || "Продавец";
        }
      } catch (e) {
        console.warn("Telegram WebApp initialization error:", e);
      }
    } else {
      // Local web fallback
      let savedId = localStorage.getItem("deal_auditor_uid");
      if (!savedId) {
        savedId = "web_" + Math.random().toString(36).substring(2, 9);
        localStorage.setItem("deal_auditor_uid", savedId);
      }
      this.userId = savedId;
    }
  },

  haptic(style = "medium") {
    if (this.isAvailable && this.tg && this.tg.HapticFeedback) {
      try {
        if (style === "success" || style === "warning" || style === "error") {
          this.tg.HapticFeedback.notificationOccurred(style);
        } else {
          this.tg.HapticFeedback.impactOccurred(style);
        }
      } catch (e) {}
    }
  }
};

window.TelegramBridge.init();
