<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body { 
            font-family: sans-serif; 
            background: var(--tg-theme-bg-color, #f0f2f5); 
            color: var(--tg-theme-text-color, #000);
            padding: 10px;
        }
        .card { background: var(--tg-theme-secondary-bg-color, #fff); border-radius: 10px; padding: 15px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { border-bottom: 1px solid #ccc; padding: 8px; text-align: left; }
    </style>
</head>
<body>
    <div class="card">
        <h3>📊 完整账单</h3>
        </div>
    <script>
        Telegram.WebApp.ready();
        Telegram.WebApp.expand(); // ขยายหน้าต่างให้เต็มจอทันที
    </script>
</body>
</html>
