---
layout: post
title: "Instagram Threads API - Part 2 - Creating Post using REST Apis"
description: "Part 2 of posting to Instagram Threads with the API: getting a long-lived token and publishing text, image and link posts with the Threads endpoints."
date: 2024-07-05 05:38:00 00
categories: automation
tags: thread instagram rest post api
author: manishtiwari25
image:
  path: /assets/img/headers/automation/thread-api-part2.webp
  alt: "Header image for Instagram Threads API Part 2: creating posts with the Threads REST API"
---

Hey there, welcome back to our journey in supercharging your Thread Account! In our [last chat](/posts/how-to-post-content-on-thread-using-api-part1), we talked about getting your hands on that special API access token tailor-made for creating posts on your Threads account. Now, armed with that token, let's dive into the fun part – crafting and scheduling posts using REST APIs.

TLDR
Please visit [https://github.com/lamplitlabs/ferret/blob/main/pkg/external/thread.go](https://github.com/lamplitlabs/ferret/blob/main/pkg/external/thread.go) for golang code.

{% include article-ads.html %}

## Why REST APIs, You Ask?

Alright, so let's break it down. REST APIs are like the magic wand for tech folks. They let you talk to all sorts of web services, and in our case, Thread's API is the one we're interested in. By tapping into these APIs, you can weave Threads right into your existing tools and workflows. It's like having a social media genie at your command, ready to whip up posts whenever you need them!

{% include article-ads.html %}

## Creating a Post

- Make sure you have the page token generated on [part 1](https://blogs.lamplitlabs.com/posts/how-to-post-on-facebook-page-using-rest-api-part1/#generate-an-api-access-token)
- Url: https://graph.threads.net/v1.0/[USER_ID]/threads?media_type=Text&text=[CONTENT_TEXT]&access_token=[ACCESS_TOKEN]
    - Method: POST
    - **Response**
      Example of a successful response
      ```json
      {
        "id": "page_post_id"
      }
      ```
- When you create a post, it will not be published, until you hit publish api.

{% include article-ads.html %}

## Publish a Post

- Url: https://graph.threads.net/v1.0/[USER_ID]/threads_publish?creation_id=[POST_ID_FROM_LAST_STEP]&access_token=[ACCESS_TOKEN]
    - Method: POST
    - **Response**
      Example of a successful response
      ```json
      {
        "id": "page_post_id"
      }
      ```

{% include article-ads.html %}

## Wrapping Up

And there you have it – a crash course in creating Threads posts like a pro using REST APIs! With these tools in your arsenal, you're ready to take your Page to new heights.

{% include article-ads.html %}

## Other

- I am not considering all the use cases here but you can visit  [https://developers.facebook.com/docs/threads](https://developers.facebook.com/docs/threads/) for more use cases.

{% include article-ads.html %}
