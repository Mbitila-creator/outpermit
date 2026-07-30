import qrcode

url = "http://192.168.10.197:8000/summit/register/"

img = qrcode.make(url)
img.save("summit_registration_qr.png")

print("QR code generated successfully.")