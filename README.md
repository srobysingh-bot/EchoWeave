# EchoWeave Home Assistant Add-ons

This repository is a Home Assistant add-on repository. It currently hosts the **EchoWeave** add-on backend, which serves as a specialized audio bridge connecting Amazon Alexa to Music Assistant.

## How to Install

You can add this repository to your Home Assistant instance by following these steps:

1. Navigate to your Home Assistant instance.
2. Go to **Settings** > **Add-ons**.
3. Click on the **Add-on Store** button in the bottom right corner.
4. Click the three-dot menu (**⋮**) in the top right corner and select **Repositories**.
5. Paste the GitHub URL of this repository (`https://github.com/srobysingh-bot/EchoWeave`) into the "Add repository" field and click **Add**.
6. Close the dialog. The new repository should appear at the bottom of the Add-on Store list.
7. Click the **EchoWeave** add-on and select **Install**.

## Important Notes & Constraints

*   **Experimental Status:** EchoWeave is currently in an experimental add-on phase. This repository only provides the backend bridge service at this time.
*   **Public HTTPS / SSL Required:** Alexa AudioPlayer skills **require** a valid, public HTTPS endpoint secured by a trusted SSL certificate. You *must* have a reverse proxy (like Nginx Proxy Manager or Cloudflare Tunnels) exposing the add-on's port to the public internet. Local IP addresses, unencrypted HTTP, and internal hostnames (like `.local`) will be rejected by Alexa and by EchoWeave's internal security validations.
