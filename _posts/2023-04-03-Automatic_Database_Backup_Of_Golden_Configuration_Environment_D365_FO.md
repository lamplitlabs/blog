---
layout: post
title: "Automatic Database Backup Of Golden Configuration Environment D365FO"
description: "Automate database backups of a D365 Finance and Operations golden configuration or tier 1/2 cloud-hosted environment with Azure DevOps and Azure Storage."
date: 2023-04-03 00:00:00 +0200
categories: coding d365 cloud
tags: d365fo powershell
author: manishtiwari25
redirect_from:
  - /blogPost/828d9714-e7b0-4099-a694-b8dc9da76d4d/automatic-database-backup-of-golden-configuration-environment-d365-fo
  - /blogPost/828d9714-e7b0-4099-a694-b8dc9da76d4d
  - /share?text=Automatic Database Backup Of Golden Configuration Environment D365FO - Lamplit Labs https://blogs.lamplitlabs.com/posts/Automatic_Database_Backup_Of_Golden_Configuration_Environment_D365_FO/
image:
  path: /assets/img/headers/d365fo.webp
  alt: Dynamics 365 Finance and Operations header image illustrating automated database backups of a golden configuration environment with Azure DevOps
---

In this article, I will talk about automated database backup of Golden Configuration Environment or any tier 1 or 2 cloud-hosted environments. <br>
we will be using Azure DevOps and Azure storage for this.

## Prerequisites

1. Must have an Azure DevOps organization
2. Must have an Azure subscription with a storage account

<br/>

![Azure DevOps pipeline that automatically backs up the D365 F&O golden configuration database](/assets/img/posts/azure-devops-d365-auto-backup.png){: width="1692" height="578" }

In this article, we will assume that our environment is stopped and we have to start it and create a backup and then stop again. <br>
In _summary_, we will be creating an Azure DevOps pipeline that will run every day(this can be hanged), start the virtual machine then run a PowerShell script in the VM which will create a backup and store it in an Azure blob.
<br/>

## Steps

- Create a library on ADO (you can name it Database-Backup, we will be needing this name later), you can follow the [official documentation](https://learn.microsoft.com/en-us/azure/devops/pipelines/library/?view=azure-devops)
- Add the following keys
  - AZBackupServiceConnection - Storage Account service connection name (follow [Official docs](https://learn.microsoft.com/en-us/azure/devops/pipelines/library/service-endpoints?view=azure-devops&tabs=yaml))
  - AZVMServiceConnection - Virtual Machine resource group service connection name
  - BlobContainer - Blob container name
  - DatabaseName - Database name (AXDb)
  - InstanceName - Database Instance (DEFAULT)
  - StorageAccount - Storage account name (where the backup file will store)
  - StorageAccountResourceGroup - storage account resource group (where the backup file will store)
  - VMName - D365 virtual machine name
  - VMResourceGroup - D365 virtual machine resource group name
- Create a new YAML file in your repository (for example pipeline-backup.yaml)
- Copy the YAML (you can find the YAML on [GitHub](https://gist.github.com/manishtiwari25/fd0f7f012455f692c26878638e48764e))
- Create a PowerShell script file (database-backup.ps1, and copy the content from [GitHub](https://gist.github.com/manishtiwari25/fd0f7f012455f692c26878638e48764e) )
- Check-In the code, if you are creating this please push the code into the repository.
- Create a new pipeline on Azure DevOps (you can get more information on [official documentation](https://learn.microsoft.com/en-us/azure/devops/pipelines/create-first-pipeline?view=azure-devops&tabs=java%2Ctfs-2018-2%2Cbrowser)), while creating the pipeline select the YAML file you created.
- Almost done, now you can run and test your pipeline (If you face any issues, please create a discussion on [GitHub](https://github.com/lamplitlabs/bites-in-byte-blog/discussions/new?category=q-a))
- Now we will create a schedule, please note this can be done in two ways
  - Adding cron in the YAML, I personally don't like this, each time I want to update the time I have to update the repository and raise a PR and then wait for approvals. you can follow the [official docs](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/scheduled-triggers?view=azure-devops&tabs=yaml) for this.
  - Adding the cron on Azure DevOps pipeline settings (classic approach). To add a schedule please follow the [official docs](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/scheduled-triggers?view=azure-devops&tabs=classic), Edit the pipeline, and then from top right menu click on trigger and create a schedule.
- Done.

## Conclusion

I hope that you are able to achieve the task. if you face any issues please raise a QA on [GitHub](https://github.com/lamplitlabs/bites-in-byte-blog/discussions/new?category=q-a).

If you are interested in terraforming, DevOps, Cloud (Azure, GCP, or AWS), or .Net, please follow me on [Medium](https://manish-tiwari.medium.com) and subscribe for the latest updates.  
 <br/>
Happy Coding, <br/>
Cheers ? _Bis Bald_

## Related posts

- [D365 FO EDMX / OData trimmer online– Make your metadata smaller online](/posts/D365_FO_EDMX_Trimmer/)
- [Navigating OData APIs with Dotnet 8 and C#: Exploring Options and Drawbacks](/posts/odata/)
- [OData Query Performance Pitfalls in .NET - $expand, Paging and Payload Size Explained](/posts/odata-query-performance-pitfalls-dotnet/)
