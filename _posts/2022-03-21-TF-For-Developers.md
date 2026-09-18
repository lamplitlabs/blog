---
layout: post
title: "Terraform for developers"
date: 2022-03-21 09:00:00 -0500
categories: terraform cloud
author: manishtiwari25
tags: terraform
image:
  path: /assets/img/headers/terraform/terraform-for-developers.webp
  alt: Terminal screenshot of the four basic Terraform commands - init, plan, apply and import
redirect_from:
  - /terraform-for-developers-150ecff176fd
  - /followers?source=user_profile-------------------------------------
---

goal of this story is to get an idea what is terraform and how an backend software engineer can use it.

I will just focus on basic functionalities which is essential for developers.

{% include article-ads.html %}

<h4>What is Terraform</h4>
you can get all the information about terraform here however in summery it is a tool written in golang by hashicorp, devops use this because it is very easy to maintain and its user friendly.

<h4>Getting Started</h4>
You can download terraform from there official website.

If you are an windows user, please add exe file in system32 folder or just add you exe path in environment.

after installing just write terraform -v in terminal/PowerShell.

{% include feed-ads.html %}

<h4>Basic Commands</h4>
as a developer you should only worry about 4 commands

1. <h6>terraform init</h6>
   this command will prepare your working directory for other commands.

2. <h6>terraform plan</h6>
   Show changes required by the current configuration, this is the most crucial step, the output of this step will give you all the things terraform will do, so before applying just make sure you are not
   destroying anything.

3. <h6>terraform apply</h6>
   Create or update infrastructure, this will trigger the cloud resources and create all the infra for you.

   {% include article-ads.html %}

4. <h6>terraform import</h6>
   Associate existing infrastructure with a Terraform resource, that means if you have existing resource in cloud it will just import there configuration in you local state.

I hope this article helps you understand something, if you have any question or you wants more stuff please add comments, I will try to add them.
