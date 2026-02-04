<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        /* ปรับดีไซน์ให้เหมือนแอปมือถือ */
        body { 
            font-family: sans-serif; 
            background-color: var(--tg-theme-bg-color, #f0f2f5); /* ใช้สีตามธีม Telegram */
            color: var(--tg-theme-text-color, #000);
        }
        .btn-close {
            background: #5c67f2; color: #fff; padding: 10px;
            border-radius: 8px; text-align: center; cursor: pointer;
        }
    </style>
</head>
<body>
    <div class="card">
        ...
    </div>

    <script>
        // ขยายหน้าจอให้เต็มทันทีที่เปิด
        Telegram.WebApp.expand();
        
        // แจ้งเตือนเมื่อกดปิด หรือทำปุ่มปิดเองในเว็บ
        function closeApp() {
            Telegram.WebApp.close();
        }
    </script>
</body>
</html>
