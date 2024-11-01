## Example HTML Code

You can use this code to check if the webpage is working properly. Copy and paste it into your HTML file, or use it in a code editor to see the button interaction.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Page</title>
    <style>
        body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }
        button { padding: 10px 20px; font-size: 16px; cursor: pointer; }
        #output { margin-top: 20px; font-weight: bold; }
    </style>
</head>
<body>
    <h1>Welcome to My Webpage</h1>
    <button onclick="showMessage()">Click Me!</button>
    <p id="output"></p>

    <script>
        function showMessage() {
            document.getElementById("output").textContent = "The page works!";
        }
    </script>
</body>
</html>
