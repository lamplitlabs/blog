---
layout: post
title: "Securing Azure APIM With Azure Key Vault"
date: 2022-12-16 09:00:00 -0500
categories: azure cloud
tags: apim key-vault
author: manishtiwari25
image:
  path: /assets/img/headers/apim-key-vault-named-value.webp
  alt: Azure portal screenshot of adding an APIM named value of type Key vault pointing at a Key Vault secret
redirect_from:
  - /securing-azure-apim-with-azure-key-vault-27bad7129e0d
  - /securing-azure-apim-with-azure-key-vault-27bad7129e0d?source=user_profile---------0----------------------------
  - /followers?source=---two_column_layout_sidebar----------------------------------
---

Azure API Gateway is a fully managed service that enables developers to create, publish, maintain, monitor, and secure APIs. Azure Key Vault is a cloud-based service that provides secure storage of secrets, such as keys, passwords, and certificates. By connecting Azure API Gateway with Azure Key Vault, you can secure your APIs by storing and managing sensitive information, such as API keys and secrets, in a secure and centralized location.

{% include article-ads.html %}

To connect Azure API Gateway with Azure Key Vault, you will need to perform the following steps:

1. Create an Azure Key Vault: If you do not already have an Azure Key Vault, you will need to create one. To do this, sign in to the Azure portal and click on “Create a resource” in the top left corner. Select “Security + Identity” from the categories and then select “Key Vault” from the list of resources. Follow the prompts to create a new Key Vault.

{% include article-ads.html %}

2. Store your secrets in Azure Key Vault: Once you have created an Azure Key Vault, you can store your secrets in it by clicking on the Key Vault and then selecting “Secrets” from the menu. Click on the “Generate/Import” button to create a new secret, and then enter the name and value of the secret you want to store.

3. Grant access to Azure API Gateway: In order for Azure API Gateway to access your secrets in Azure Key Vault, you will need to grant it access. To do this, click on the Key Vault and then select “Access policies” from the menu. Click on the “Add Access Policy” button and then select “API Management” from the list of services. Follow the prompts to grant Azure API Gateway access to your Key Vault.

4. Configure Azure API Gateway to use Azure Key Vault: Once you have granted Azure API Gateway access to your Azure Key Vault, you can configure your API Gateway to use it. To do this, sign in to the Azure portal and navigate to your API Gateway. Select the API you want to secure and then click on “Policies” in the menu. Add the following policy to your API:

```xml
<policies>
  <inbound>
    <base />
    <key-vault-configuration resourceId="<YOUR KEY VAULT RESOURCE ID>" secretName="<YOUR SECRET NAME>" />
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
```

{% include feed-ads.html %}

5. Test your API: Once you have configured your API Gateway to use Azure Key Vault, you can test your API to ensure that it is working correctly. To do this, send a request to your API and verify that you receive the expected response.

By following these steps, you can securely connect Azure API Gateway with Azure Key Vault and store and manage your secrets in a centralized location. This can help you secure your APIs and protect sensitive information, such as API keys and secrets, from unauthorized access.
