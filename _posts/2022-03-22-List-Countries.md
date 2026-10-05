---
layout: post
title: "Where can I get list of countries and there state provinces?"
description: "A free, automatically updated list of all countries with their states and provinces, ready to use in your project as JSON."
date: 2022-03-22 09:00:00 -0500
categories: cloud gist
tags: Countries Geoname Gist
author: manishtiwari25
image:
  path: /assets/img/headers/list-countries-states-gist.webp
  alt: JSON snippet from the countries gist showing a country with its ISO code and nested list of states and provinces
redirect_from:
  - /where-can-i-get-list-of-countries-and-there-state-provinces-f05ce8f50928
  - /where-can-i-get-list-of-countries-and-there-state-provinces-f05ce8f50928?source=user_profile---------4----------------------------
  - /share?text=Where can I get list of countries and there state provinces? - Lamplit Labs https://blogs.lamplitlabs.com/posts/List-Countries/
---

Last year when I was working on a project I also came across same question, I did some research I manage to find few sources but all of them were outdated so I decided to create my own gist for that.

{% include article-ads.html %}

this contains all the countries and there states and this list will update automatically every month so you don’t have to worry about outdated data.

I am using geonames dumps to create this gist so if you find any incorrect data you can update at geonames side and it will reflect in next release.

Here is the JSON shape each country entry follows in the gist, with its ISO codes and nested list of states/provinces:

![Example JSON entry for Canada showing name, iso2, iso3 fields and a nested states array with Ontario and Quebec entries, each carrying a name and state_code](/assets/img/posts/gist/countries-states-json-shape.webp)
*Each country object carries `name`, `iso2`, `iso3`, and a `states` array - use `state_code` to match a province/state back to its parent country.*

{% include feed-ads.html %}

[Here](https://gist.github.com/manishtiwari25/0fa055ee14f29ee6a7654d50af20f095) you can find the gist.
