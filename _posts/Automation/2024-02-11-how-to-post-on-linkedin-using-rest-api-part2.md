---
layout: post
title: "Unlocking LinkedIn's Posting Potential: Part 2 - Creating Post using REST Apis"
description: "Part 2 of automating LinkedIn posts with the REST API: finding your author URN and publishing text, article links and images with the Posts endpoint."
date: 2024-02-11 05:38:00 +0000
categories: automation
tags: linkedin rest post api
author: manishtiwari25
image:
  path: /assets/img/headers/automation/unlock-your-linkedin-posting-potential-2.webp
  alt: LinkedIn automation header image illustrating creating posts programmatically with the LinkedIn REST Posts API in part 2 of the series
---

## Introduction

Welcome back to the second installment of our series on leveraging the LinkedIn API! In [the previous part](/posts/how-to-post-on-linkedin-using-rest-api-part1), we navigated through the intricacies of obtaining the access token, a crucial step in communicating with LinkedIn's API. Now that we have our access token securely in hand, we're poised to dive deeper into the exciting world of content creation and publishing on LinkedIn.

In this part, we'll build upon the foundation we established in Part 1, exploring how to use the access token to craft and publish engaging content seamlessly. From formulating compelling posts to utilizing the REST API endpoints, we'll walk you through each step with clarity and simplicity.

So, if you're ready to take your LinkedIn presence to new heights, grab your favorite beverage, settle in, and let's embark on the next leg of our journey together. Whether you're a seasoned professional or just starting your LinkedIn adventure, rest assured that I'm here to guide you every step of the way.

Let's dive in!

{% include article-ads.html %}

## How does LinkedIn v2/posts Api work?

![How API Works](/assets/img/posts/automation/linkedin-automation/api-flow.webp)

1.  #### Fetch Profile Information

    Before we create a post, we'll need to fetch the user's profile information. This step is essential because we require the user ID to associate the post with the correct LinkedIn account.

    - Url: https://api.linkedin.com/v2/userinfo
    - Method: Get
    - Headers

      - Authentication: Bearer ACCESS_TOKEN

      ```bash
        curl --location 'https://api.linkedin.com/v2/userinfo' --header 'Authorization: Bearer '
      ```

    - <strong> Response </strong>

      ```json
      {
        "sub": "",
        "email_verified": true,
        "name": "",
        "locale": {
          "country": "US",
          "language": "en"
        },
        "given_name": "",
        "family_name": "",
        "email": "",
        "picture": ""
      }
      ```

      We will be using the value of the sub for future purposes.

{% include article-ads.html %}

2.  #### Upload Images (if any)

    If our post includes images, we'll need to upload them to LinkedIn's servers. This step ensures that our post displays correctly, especially for article previews or image-rich content.

    - ##### Fetch Upload URL

      To upload the image, we need to fetch the upload URL.

      - Url: https://api.linkedin.com/rest/images?action=initializeUpload
      - Method: POST
      - Headers
        - Authentication: Bearer ACCESS_TOKEN
        - LinkedIn-Version: 202401 (try to use any latest version)
        - X-RestLi-Protocol-Version: 2.0.0
        - Content-Type: application/json
      - Content:

      ```json
      {
        "initializeUploadRequest": {
          "owner": "urn:li:person:ID"
        }
      }
      ```

      ```bash
        curl --location 'https://api.linkedin.com/rest/images?action=initializeUpload' \
        --header 'X-RestLi-Protocol-Version: 2.0.0' \
        --header 'LinkedIn-Version: 202401' \
        --header 'Content-Type: application/json' \
        --header 'Authorization: Bearer TOKEN' \
        --data '{
          "initializeUploadRequest": {
          "owner": "urn:li:person:ID" //REPLACE ID
          }
        }'
      ```

      - <strong> Response </strong>

      ```json
      {
        "value": {
          "uploadUrlExpiresAt": ,
          "uploadUrl": "",
        "image": "urn:li:image:"
        }
      }
      ```

      We will be using the value of the image for generating the url preview and uploadUrl for uploading the image

      For More Please Visit [LinkedIn API Documentation](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api?view=li-lms-2024-01&tabs=http)

      - ##### Upload the Image

      ```bash
        curl --location --request PUT 'https://www.linkedin.com/dms-uploads/sp/' \
        --form 'file=@"android-chrome-512x512.png"'
      ```

{% include article-ads.html %}

3.  #### Create Post

    Finally, armed with the necessary profile information and any uploaded images, we'll create our post using LinkedIn's REST API endpoints. We'll explore how to formulate compelling posts and publish them seamlessly to engage our audience effectively.

    - Url: https://api.linkedin.com/v2/posts
    - Method: POST
    - Headers
      - Authentication: Bearer ACCESS_TOKEN
      - LinkedIn-Version: 202401 (try to use any latest version)
      - X-RestLi-Protocol-Version: 2.0.0
      - Content-Type: application/json
    - Content:

    ```json
    {
      "author": "urn:li:person:",
      "commentary": "",
      "visibility": "PUBLIC",
      "contentLandingPage": "",
      "distribution": {
        "feedDistribution": "MAIN_FEED"
      },
      "content": {
        "article": {
          "source": "",
          "title": "",
          "description": "",
          "thumbnail": "urn:li:image:"
        }
      },
      "lifecycleState": "PUBLISHED",
      "isReshareDisabledByAuthor": false,
      "contentCallToActionLabel": "SEE_MORE"
    }
    ```

    For more properties, please visit [LinkedIn API Documentation](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2024-01&tabs=http)

{% include article-ads.html %}

## Conclusion

In this second part of our series on leveraging the LinkedIn API, we've explored the process of crafting and publishing posts with simplicity and efficiency.

We began by fetching the user's profile information, ensuring that we had the necessary details, such as the user ID, to associate our post correctly. Next, we addressed the importance of uploading images, especially for visually rich content like article previews, to enhance the engagement of our posts.

Finally, armed with the profile information and any uploaded images, we seamlessly created our posts using LinkedIn's REST API endpoints. By following these steps, we've unlocked the power to engage our audience effectively and elevate our presence on LinkedIn.

As you continue your journey into content creation and networking on LinkedIn, remember that practice makes perfect. Experiment with different types of posts, analyze their performance and iterate on your strategy to optimize your results.

Keep crafting compelling content, keep networking, and most importantly, keep shining on LinkedIn!

Let's keep moving forward together!

{% include article-ads.html %}

## Other

- Go Code is available [here](https://github.com/lamplitlabs/ferret/blob/main/pkg/external/linkedin.go)

## Related posts

- [Unlocking LinkedIn's Posting Potential: Part 1 - Obtaining Your API Access Token](/posts/how-to-post-on-linkedin-using-rest-api-part1/)
- [Maximizing Your Facebook Page: Part 2 - Creating Post using REST Apis](/posts/how-to-post-on-facebook-page-using-rest-api-part2/)
- [Automating RSS Feed Posts to Twitter(X) and Mastodon Using Logic Apps](/posts/auto-post-RSS-feed-to-twitter-and-mastodon-using-logicapps/)
