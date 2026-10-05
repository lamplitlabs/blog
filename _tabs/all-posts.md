---
title: All Posts
icon: fas fa-list
order: 1
---

Every post on the blog in one flat list, newest first, with its categories so you
can jump straight to the topic you care about. For a year-by-year view use the
[Archives]({{ '/archives/' | relative_url }}) tab.

<ul class="list-unstyled" id="all-posts">
{% for post in site.posts %}
  <li class="mb-3">
    <a href="{{ post.url | relative_url }}" class="fw-bold">{{ post.title }}</a>
    <div class="small text-muted">
      <time datetime="{{ post.date | date_to_xmlschema }}">{{ post.date | date: '%b %-d, %Y' }}</time>
      {% if post.categories.size > 0 %}
      &middot;
      {% for category in post.categories %}
        <a href="{{ category | slugify | prepend: '/categories/' | append: '/' | relative_url }}">{{ category }}</a>{% unless forloop.last %}, {% endunless %}
      {% endfor %}
      {% endif %}
    </div>
    {% if post.description %}<p class="mb-0 small">{{ post.description }}</p>{% endif %}
  </li>
{% endfor %}
</ul>
