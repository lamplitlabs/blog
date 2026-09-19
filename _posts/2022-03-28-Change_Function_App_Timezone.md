---
layout: post
title: "How To Change Azure Function App Time zone"
date: 2022-03-28 09:00:00 -0500
categories: cloud function azure
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

{% include article-ads.html %}

<strong>Using Azure portal</strong>

- Go to the azure function app configurations
- Add a new Configuration `WEBSITE_TIME_ZONE`
- For windows possible values listed [here](<https://docs.microsoft.com/en-us/previous-versions/windows/it-pro/windows-vista/cc749073(v=ws.10)?redirectedfrom=MSDN#time-zones>)
- For Linux possible values listed [here](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)
- Save the configuration
- Done

{% include article-ads.html %}

<strong>Using PowerShell</strong>

Run following command and add a new app settings, don’t forget to change the values (for windows, for Linux)

```bash
Update-AzFunctionAppSetting -Name <MyAppName> -ResourceGroupName <MyResourceGroupName> -AppSetting @{"WEBSITE_TIME_ZONE" = "CHANGE_THIS"}
```

{% include article-ads.html %}

If you face any issues or if you have any question please add a comment, and please don’t forget to follow me.

cheers🍻
