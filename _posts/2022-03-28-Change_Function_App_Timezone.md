---
layout: post
title: "How To Change Azure Function App Time zone"
description: "How to change the time zone used by Azure Function App timer triggers with the WEBSITE_TIME_ZONE setting so CRON expressions run in local time."
date: 2022-03-28 00:00:00 +0200
categories: cloud function azure lamplit-tools
tags: azure azurefunction
author: manishtiwari25
image:
  path: /assets/img/headers/function-app-website-time-zone.webp
  alt: Azure portal screenshot of a Function App Configuration blade with the WEBSITE_TIME_ZONE application setting highlighted
redirect_from:
  - /how-to-change-azure-function-app-time-zone-a9c256fee353?source=user_profile---------3----------------------------
  - /how-to-change-azure-function-app-time-zone-a9c256fee353
  - /how-to-change-azure-function-app-time-zone-a9c256fee353?source=post_internal_links---------0----------------------------
  - /how-to-change-azure-function-app-time-zone-a9c256fee353?source=post_internal_links---------5----------------------------
  - /how-to-change-azure-function-app-time-zone-a9c256fee353?source=author_recirc-----891e3866d81----2----------------------------
---

Azure function app uses [NCronTab](https://github.com/atifaziz/NCrontab) library to interpret the CRON expression.
you can test your expression [here](https://tools.lamplitlabs.com/cron).
By default Azure function app uses UTC Timezone.

Now lets get to the point, before starting please check whether your function app is using Windows or Linux.

<strong>Using Azure portal</strong>

- Go to the azure function app configurations
- Add a new Configuration `WEBSITE_TIME_ZONE`
- For windows possible values listed [here](<https://docs.microsoft.com/en-us/previous-versions/windows/it-pro/windows-vista/cc749073(v=ws.10)?redirectedfrom=MSDN#time-zones>)
- For Linux possible values listed [here](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)
- Save the configuration
- Done

![Azure Function App configuration showing the WEBSITE_TIME_ZONE application setting](/assets/img/posts/azure/function-app-website-time-zone-setting.webp){: width="1200" height="614" }
*In the portal open your Function App → **Settings → Environment variables → App settings** (older portals: **Configuration → Application settings**), click **Add**, enter `WEBSITE_TIME_ZONE` as the name and your time-zone id as the value, then **Apply/Save**. The app restarts and timer triggers start firing in that zone.*

<strong>Using PowerShell</strong>

Run following command and add a new app settings, don’t forget to change the values (for windows, for Linux)

```bash
Update-AzFunctionAppSetting -Name <MyAppName> -ResourceGroupName <MyResourceGroupName> -AppSetting @{"WEBSITE_TIME_ZONE" = "CHANGE_THIS"}
```

If you face any issues or if you have any question please add a comment, and please don’t forget to follow me.

cheers🍻

*Inline screenshot: Function App app settings blade, from [Microsoft Learn – Manage your function app](https://learn.microsoft.com/azure/azure-functions/functions-how-to-use-azure-function-app-settings), © Microsoft, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).*

## Related posts

- [Updating Azure Function App From V3 to V4](/posts/Updating-Azure-Function-v3-v4/)
- [Azurite + GitHub Actions](/posts/Azurite-GitHubAction/)
- [Securing Azure APIM With Azure Key Vault](/posts/APIM-Key-Vault/)
