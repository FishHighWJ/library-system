/**
 * 图书馆管理系统 - 前端交互逻辑
 * 增强版：防重复提交、加载状态、确认弹窗
 */

document.addEventListener("DOMContentLoaded", function () {

    // ==== 1. 防重复提交 ====
    // 所有 POST 表单提交后禁用提交按钮，防止用户快速多次点击
    const forms = document.querySelectorAll('form[method="POST"], form[method="post"]');
    forms.forEach(form => {
        form.addEventListener('submit', function (e) {
            // 跳过搜索表单
            if (form.classList.contains('search-form')) return;

            const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
            if (!submitBtn) return;

            // 禁用按钮
            if (submitBtn.tagName === 'BUTTON') {
                const originalText = submitBtn.innerHTML;
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> 处理中...';

                // 10秒后自动恢复（防止永久禁用）
                setTimeout(() => {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = originalText;
                }, 10000);
            }
        });
    });

    // ==== 2. 删除确认弹窗 ====
    const deleteForms = document.querySelectorAll('.confirm-delete, form[data-confirm]');
    deleteForms.forEach(form => {
        form.addEventListener('submit', function (e) {
            const message = form.dataset.confirm || '确定要删除吗？此操作不可撤销。';
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });

    // ==== 3. 借阅确认弹窗 ====
    const borrowForms = document.querySelectorAll('.confirm-borrow');
    borrowForms.forEach(form => {
        form.addEventListener('submit', function (e) {
            const bookTitle = form.dataset.title || '此书';
            if (!confirm(`确定要借阅《${bookTitle}》吗？\n借阅期限30天，逾期0.5元/天。`)) {
                e.preventDefault();
            }
        });
    });

    // ==== 4. 还书确认弹窗 ====
    const returnForms = document.querySelectorAll('.confirm-return');
    returnForms.forEach(form => {
        form.addEventListener('submit', function (e) {
            if (!confirm('确定要归还这本书吗？')) {
                e.preventDefault();
            }
        });
    });

    // ==== 5. 分类筛选数字动画 ====
    const categoryBadges = document.querySelectorAll('.category-count');
    categoryBadges.forEach(badge => {
        const count = parseInt(badge.textContent);
        if (count === 0) {
            badge.classList.add('bg-danger');
            badge.classList.remove('bg-secondary');
        } else if (count <= 2) {
            badge.classList.add('bg-warning', 'text-dark');
            badge.classList.remove('bg-secondary');
        }
    });

    // ==== 6. 可借数量颜色提示 ====
    const availabilityBadges = document.querySelectorAll('.availability-badge');
    availabilityBadges.forEach(badge => {
        const text = badge.textContent;
        const match = text.match(/(\d+)\/(\d+)/);
        if (match) {
            const available = parseInt(match[1]);
            const total = parseInt(match[2]);
            if (available === 0) {
                badge.className = 'badge bg-danger availability-badge';
                badge.textContent = '已借完';
            } else if (available <= total * 0.3) {
                badge.className = 'badge bg-warning text-dark availability-badge';
            }
        }
    });

    // ==== 7. 自动刷新数据看板（管理员） ====
    // 改为 fetch 局部刷新：避免整页 reload 销毁 ECharts 实例，刷新后只更新数据
    const dashboard = document.querySelector('.dashboard-page');
    if (dashboard) {
        setInterval(() => {
            if (document.hidden) return;
            // 看板暴露了 window.__dashboard.update(data)，fetch 后调用即可
            if (!window.__dashboard) return;
            fetch("/dashboard/api/data", { credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) { if (data) window.__dashboard.update(data); })
                .catch(function (err) { console.warn('看板刷新失败:', err); });
        }, 60000);
    }

    // ==== 8. 搜索框防抖 ====
    const searchInput = document.querySelector('input[name="keyword"]');
    if (searchInput) {
        let searchTimer = null;
        searchInput.addEventListener('input', function () {
            clearTimeout(searchTimer);
            // 如果输入为空，自动提交（重置）
            if (this.value === '') {
                searchTimer = setTimeout(() => {
                    this.form.submit();
                }, 500);
            }
        });
    }

    // ==== 9. Toast 通知（替代alert） ====
    // 检测flash消息并自动消失
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        // 5秒后自动消失
        setTimeout(() => {
            alert.classList.remove('show');
            setTimeout(() => alert.remove(), 300);
        }, 5000);
    });

    // ==== 10. 输入验证 ====
    // ISBN 输入只允许数字和X
    const isbnInput = document.querySelector('input[name="isbn"]');
    if (isbnInput) {
        isbnInput.addEventListener('input', function () {
            this.value = this.value.replace(/[^0-9Xx]/g, '').toUpperCase();
        });
    }

    // 价格输入只允许数字和小数点
    const priceInput = document.querySelector('input[name="price"]');
    if (priceInput) {
        priceInput.addEventListener('input', function () {
            this.value = this.value.replace(/[^0-9.]/g, '');
        });
    }

    // 数量输入只允许正整数
    const countInputs = document.querySelectorAll('input[name="total_count"]');
    countInputs.forEach(input => {
        input.addEventListener('input', function () {
            this.value = this.value.replace(/[^0-9]/g, '');
            if (parseInt(this.value) < 1) this.value = 1;
        });
    });
});
