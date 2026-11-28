#!/usr/bin/env ruby
#
# Renamed posts keep answering to their old name in {% post_url %}.
#
# A post's file name is its address, in the URL and in every
# `{% post_url AI/2026-10-25-name %}` another post writes. When a post is
# renamed, a branch that was written before the rename still carries the old
# name, and the build of the merged result stops with
# `Could not find post "..." in tag 'post_url'`: nothing is deployed until
# someone edits that one line. The table below maps an old name to the new
# one, so such a branch builds and its link goes straight to the renamed post.
#
# This is a bridge, not a licence: tools/test.sh (check_old_product_name)
# still fails on the old names, so they get fixed. The old URLs themselves
# are forwarded by the pages in /redirects/.
#
# Add a row when a published post is renamed; rows never need removing.

module PostUrlAliases
  RENAMED = {
    # 2026-11-27: the product "Pulse" shipped as Hive (https://hivefleet.dev).
    'AI/2026-10-25-pulse-internal-rsi-tool' => 'AI/2026-10-25-hive-self-improving-rsi-agent-harness',
    'AI/2026-10-12-pulse-automation-evolution' => 'AI/2026-10-12-hive-automation-evolution'
  }.freeze

  def initialize(tag_name, post, tokens)
    name = post.to_s.strip.sub(%r{\A/}, '')
    super(tag_name, RENAMED.fetch(name, post), tokens)
  end
end

Jekyll::Tags::PostUrl.prepend(PostUrlAliases)
