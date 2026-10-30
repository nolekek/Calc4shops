document.addEventListener("alpine:init", () => {
  Alpine.data("dealAuditorApp", () => ({
    // State
    activeTab: "audit", // 'audit', 'reverse', 'history', 'settings'
    isLoading: false,
    copyToast: false,

    // Dictionaries
    platforms: [],
    taxRegimes: [],
    rates: {},

    // Forward Audit Form
    form: {
      cost: 500,
      currency: "RUB",
      currencyRate: 1.0,
      price: 1000,
      platform: "plati",
      taxRegime: "npd_6",
      targetMargin: 20,
      // Detailed overrides
      showAdvanced: false,
      platFeePct: null,
      platFeeFixed: 0,
      payFeePct: null,
      payFeeFixed: 0,
      payOnNet: true
    },

    // Reverse Finder Form
    reverseForm: {
      cost: 500,
      currency: "RUB",
      currencyRate: 1.0,
      mode: "target_profit", // 'target_profit' or 'target_margin'
      targetValue: 300,
      platform: "plati",
      taxRegime: "npd_6"
    },

    // Calculated Results
    result: null,
    reverseResult: null,
    historyList: [],

    // Batch / CSV State
    batchItems: [],
    batchSummary: null,
    batchFilter: "all",
    isBatchLoading: false,

    async init() {
      await this.loadPresetsAndRates();
      await this.loadUserSettings();
      this.recalculate();
    },

    async loadPresetsAndRates() {
      try {
        const [presetsRes, ratesRes] = await Promise.all([
          fetch("/api/presets").then(r => r.json()),
          fetch("/api/rates").then(r => r.json())
        ]);
        this.platforms = presetsRes.platforms || [];
        this.taxRegimes = presetsRes.tax_regimes || [];
        this.rates = ratesRes || {};
        this.updateRateForCurrency();
      } catch (e) {
        console.error("Error loading presets/rates:", e);
      }
    },

    async loadUserSettings() {
      try {
        const uid = window.TelegramBridge.userId;
        const res = await fetch(`/api/settings/${uid}`).then(r => r.json());
        if (res) {
          if (res.default_platform) this.form.platform = res.default_platform;
          if (res.default_tax_regime) this.form.taxRegime = res.default_tax_regime;
          if (res.default_currency) this.form.currency = res.default_currency;
          if (res.target_margin_pct) this.form.targetMargin = res.target_margin_pct;
          this.updateRateForCurrency();
        }
      } catch (e) {
        console.warn("Could not load user settings:", e);
      }
    },

    setTab(tab) {
      this.activeTab = tab;
      window.TelegramBridge.haptic("light");
      if (tab === "history") {
        this.loadHistory();
      } else if (tab === "reverse") {
        this.recalculateReverse();
      }
    },

    selectPlatform(platId) {
      this.form.platform = platId;
      this.reverseForm.platform = platId;
      const p = this.platforms.find(x => x.id === platId);
      if (p) {
        this.form.platFeePct = p.platform_fee_pct;
        this.form.platFeeFixed = p.platform_fee_fixed;
        this.form.payFeePct = p.payout_fee_pct;
        this.form.payFeeFixed = p.payout_fee_fixed;
      }
      window.TelegramBridge.haptic("selection");
      this.recalculate();
    },

    selectCurrency(curr) {
      this.form.currency = curr;
      this.reverseForm.currency = curr;
      this.updateRateForCurrency();
      window.TelegramBridge.haptic("selection");
      this.recalculate();
    },

    updateRateForCurrency() {
      const c = this.form.currency;
      if (this.rates && this.rates[c]) {
        this.form.currencyRate = this.rates[c].rate_to_rub;
        this.reverseForm.currencyRate = this.rates[c].rate_to_rub;
      } else {
        this.form.currencyRate = 1.0;
        this.reverseForm.currencyRate = 1.0;
      }
    },

    quickAdjust(field, amount) {
      if (field === 'cost') {
        this.form.cost = Math.max(0, (Number(this.form.cost) || 0) + amount);
      } else if (field === 'price') {
        this.form.price = Math.max(0, (Number(this.form.price) || 0) + amount);
      } else if (field === 'reverseCost') {
        this.reverseForm.cost = Math.max(0, (Number(this.reverseForm.cost) || 0) + amount);
      } else if (field === 'reverseTarget') {
        this.reverseForm.targetValue = Math.max(0, (Number(this.reverseForm.targetValue) || 0) + amount);
      }
      window.TelegramBridge.haptic("light");
      this.recalculate();
      if (this.activeTab === 'reverse') this.recalculateReverse();
    },

    _debounceTimer: null,
    recalculate() {
      clearTimeout(this._debounceTimer);
      this._debounceTimer = setTimeout(() => {
        this._doCalculate();
      }, 120);
    },

    async _doCalculate() {
      const cost = Number(this.form.cost) || 0;
      const price = Number(this.form.price) || 0;
      if (price <= 0) return;

      const payload = {
        user_id: window.TelegramBridge.userId,
        cost_original: cost,
        currency: this.form.currency,
        currency_rate: Number(this.form.currencyRate) || 1.0,
        price: price,
        platform_id: this.form.platform,
        platform_fee_pct: this.form.platFeePct !== null ? Number(this.form.platFeePct) : null,
        platform_fee_fixed: Number(this.form.platFeeFixed) || 0,
        payout_fee_pct: this.form.payFeePct !== null ? Number(this.form.payFeePct) : null,
        payout_fee_fixed: Number(this.form.payFeeFixed) || 0,
        payout_fee_on_net: this.form.payOnNet,
        tax_regime: this.form.taxRegime,
        target_margin_pct: Number(this.form.targetMargin) || 20.0,
        save_to_history: false // only explicit or background save
      };

      try {
        const res = await fetch("/api/calculate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        }).then(r => r.json());

        this.result = res;
      } catch (e) {
        console.error("Calculation failed:", e);
      }
    },

    async saveDealToHistory() {
      if (!this.result) return;
      window.TelegramBridge.haptic("success");
      const cost = Number(this.form.cost) || 0;
      const price = Number(this.form.price) || 0;

      const payload = {
        user_id: window.TelegramBridge.userId,
        cost_original: cost,
        currency: this.form.currency,
        currency_rate: Number(this.form.currencyRate) || 1.0,
        price: price,
        platform_id: this.form.platform,
        platform_fee_pct: this.form.platFeePct !== null ? Number(this.form.platFeePct) : null,
        platform_fee_fixed: Number(this.form.platFeeFixed) || 0,
        payout_fee_pct: this.form.payFeePct !== null ? Number(this.form.payFeePct) : null,
        payout_fee_fixed: Number(this.form.payFeeFixed) || 0,
        payout_fee_on_net: this.form.payOnNet,
        tax_regime: this.form.taxRegime,
        target_margin_pct: Number(this.form.targetMargin) || 20.0,
        save_to_history: true
      };

      try {
        await fetch("/api/calculate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        this.triggerCopyToast("Расчёт сохранён в историю!");
      } catch (e) {
        console.error("Failed to save history:", e);
      }
    },

    async recalculateReverse() {
      const cost = Number(this.reverseForm.cost) || 0;
      const targetVal = Number(this.reverseForm.targetValue) || 0;
      if (targetVal <= 0) return;

      const payload = {
        cost_original: cost,
        currency: this.reverseForm.currency,
        currency_rate: Number(this.reverseForm.currencyRate) || 1.0,
        mode: this.reverseForm.mode,
        target_value: targetVal,
        platform_id: this.reverseForm.platform,
        tax_regime: this.reverseForm.taxRegime,
        target_margin_pct: Number(this.form.targetMargin) || 20.0
      };

      try {
        const res = await fetch("/api/calculate/reverse", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        }).then(r => r.json());
        this.reverseResult = res;
      } catch (e) {
        console.error("Reverse calculation failed:", e);
      }
    },

    async loadHistory() {
      try {
        const uid = window.TelegramBridge.userId;
        const res = await fetch(`/api/history/${uid}?limit=15`).then(r => r.json());
        this.historyList = res || [];
      } catch (e) {
        console.error("Failed to load history:", e);
      }
    },

    async saveSettings() {
      window.TelegramBridge.haptic("success");
      const uid = window.TelegramBridge.userId;
      const payload = {
        user_id: uid,
        default_platform: this.form.platform,
        default_tax_regime: this.form.taxRegime,
        default_currency: this.form.currency,
        target_margin_pct: Number(this.form.targetMargin) || 20.0,
        custom_platform_fee_pct: this.form.platFeePct !== null ? Number(this.form.platFeePct) : null,
        custom_payout_fee_pct: this.form.payFeePct !== null ? Number(this.form.payFeePct) : null,
        custom_payout_fee_fixed: Number(this.form.payFeeFixed) || 0
      };

      try {
        await fetch(`/api/settings/${uid}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        this.triggerCopyToast("Настройки успешно сохранены!");
      } catch (e) {
        console.error("Failed to save settings:", e);
      }
    },

    copySummary() {
      if (!this.result) return;
      window.TelegramBridge.haptic("success");
      const r = this.result;
      const text = 
`📊 Аудит сделки [${this.form.platform.toUpperCase()}]
• Выручка: ${r.gross_revenue} ₽
• Себестоимость: ${r.cost_rub} ₽ (${this.form.cost} ${this.form.currency})
• Комиссия площадки: ${r.platform_fee} ₽ (${r.platform_fee_pct_applied}%)
• Вывод: ${r.payout_fee} ₽ (${r.payout_fee_pct_applied}%)
• Налог: ${r.tax_amount} ₽ (${r.tax_rate_pct_applied}%)
💰 ЧИСТАЯ ПРИБЫЛЬ: ${r.net_profit > 0 ? '+' : ''}${r.net_profit} ₽ (маржа ${r.margin_pct}%)
🎯 Точка безубыточности: ${r.breakeven_price} ₽
🛡️ Макс. скидка: ${r.max_discount_rub} ₽
Вердикт: ${r.verdict_title}`;

      navigator.clipboard.writeText(text).then(() => {
        this.triggerCopyToast("Расчёт скопирован в буфер!");
      });
    },

    // --- BATCH CSV ACTIONS ---
    async loadDemoBatch() {
      this.isBatchLoading = true;
      window.TelegramBridge.haptic("medium");
      try {
        const res = await fetch("/api/batch/demo", { method: "POST" }).then(r => r.json());
        this.batchItems = res.items || [];
        this.batchSummary = res.summary || null;
        this.triggerCopyToast("Загружен демо-прайс (5 лотов)!");
      } catch (e) {
        console.error("Failed demo batch:", e);
      } finally {
        this.isBatchLoading = false;
      }
    },

    async handleFileUpload(e) {
      const file = e.target.files[0];
      if (!file) return;
      this.isBatchLoading = true;
      window.TelegramBridge.haptic("medium");
      const formData = new FormData();
      formData.append("file", file);

      try {
        const resp = await fetch("/api/batch/upload-csv", {
          method: "POST",
          body: formData
        });
        if (!resp.ok) {
          const err = await resp.json();
          alert(err.detail || "Ошибка при обработке CSV");
          return;
        }
        const data = await resp.json();
        this.batchItems = data.items || [];
        this.batchSummary = data.summary || null;
        window.TelegramBridge.haptic("success");
        this.triggerCopyToast(`Успешно проверено ${this.batchItems.length} лотов!`);
      } catch (err) {
        console.error("Upload error:", err);
      } finally {
        this.isBatchLoading = false;
        e.target.value = "";
      }
    },

    async downloadAuditedCsv() {
      if (!this.batchItems.length) return;
      window.TelegramBridge.haptic("success");
      try {
        const resp = await fetch("/api/batch/export-csv", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(this.batchItems)
        });
        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "audited_price_list.csv";
        document.body.appendChild(a);
        a.click();
        a.remove();
        this.triggerCopyToast("Файл отчёта скачан!");
      } catch (e) {
        console.error("Download error:", e);
      }
    },

    get filteredBatchItems() {
      if (this.batchFilter === "unprofitable") {
        return this.batchItems.filter(x => x.verdict === "unprofitable");
      }
      if (this.batchFilter === "borderline") {
        return this.batchItems.filter(x => x.verdict === "borderline");
      }
      return this.batchItems;
    },

    triggerCopyToast(msg) {
      this.toastMessage = msg;
      this.copyToast = true;
      setTimeout(() => {
        this.copyToast = false;
      }, 2200);
    }
  }));
});
