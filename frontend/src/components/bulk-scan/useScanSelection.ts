import { useCallback, useMemo, useState } from "react";
import type { DiscoveredMediaItem } from "../../../../desktop/shared/types";
import { isItemDownloaded, type PostWithScan } from "./types";
import { visibleMedia } from "./utils";

/** Selection is independent from filtering. */
export function useScanSelection(
  posts: PostWithScan[],
  visiblePosts: PostWithScan[],
  filter: "all" | "image" | "video" | "album",
  downloaded: Set<string>
) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const visibleItems = useMemo(
    () => visiblePosts.flatMap((post) => visibleMedia(post, filter)),
    [visiblePosts, filter]
  );

  const selectedItems = useMemo<DiscoveredMediaItem[]>(() => {
    if (selected.size === 0) return [];
    return posts
      .flatMap((post) => post.media_items)
      .filter((item) => selected.has(item.id));
  }, [posts, selected]);

  const toggleMedia = useCallback((itemId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }, []);

  const togglePost = useCallback((post: PostWithScan) => {
    const ids = post.media_items.map((item) => item.id);
    setSelected((prev) => {
      const allSelected = ids.length > 0 && ids.every((id) => prev.has(id));
      const next = new Set(prev);
      for (const id of ids) {
        if (allSelected) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  }, []);

  const selectAllVisible = useCallback(
    () => setSelected(new Set(visibleItems.map((item) => item.id))),
    [visibleItems]
  );

  const selectOnlyNew = useCallback(
    () =>
      setSelected(
        new Set(visibleItems.filter((item) => !isItemDownloaded(item, downloaded)).map((item) => item.id))
      ),
    [visibleItems, downloaded]
  );

  const clearSelection = useCallback(() => setSelected(new Set()), []);

  const selectByType = useCallback(
    (type: "image" | "video") =>
      setSelected(
        new Set(visibleItems.filter((item) => item.media_type === type).map((item) => item.id))
      ),
    [visibleItems]
  );

  const selectAlbums = useCallback(
    () =>
      setSelected(
        new Set(
          visiblePosts
            .filter((post) => post.media_items.length > 1)
            .flatMap((post) => visibleMedia(post, filter))
            .map((item) => item.id)
        )
      ),
    [visiblePosts, filter]
  );

  const invertSelection = useCallback(
    () =>
      setSelected(
        new Set(visibleItems.filter((item) => !selected.has(item.id)).map((item) => item.id))
      ),
    [selected, visibleItems]
  );

  return {
    selected,
    selectedItems,
    visibleItems,
    toggleMedia,
    togglePost,
    selectAllVisible,
    selectOnlyNew,
    clearSelection,
    selectByType,
    selectAlbums,
    invertSelection,
  };
}
