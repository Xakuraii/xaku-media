import { useCallback, useMemo, useState } from "react";
import type { DiscoveredMediaItem } from "../../../../desktop/shared/types";
import { isItemHandled, isItemSkipped, type PostWithScan } from "./types";
import { visibleMedia } from "./utils";

/** Selection is independent from filtering. */
export function useScanSelection(
  posts: PostWithScan[],
  visiblePosts: PostWithScan[],
  filter: "all" | "image" | "video" | "album",
  downloaded: Set<string>,
  skipped: Set<string> = new Set(),
  showNewOnly: boolean = false,
  hideSkipped: boolean = false
) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const visibleItems = useMemo(
    () =>
      visiblePosts
        .flatMap((post) => visibleMedia(post, filter))
        .filter(
          (item) =>
            (!showNewOnly || !isItemHandled(item, downloaded, skipped)) &&
            (!hideSkipped || !isItemSkipped(item, skipped))
        ),
    [visiblePosts, filter, downloaded, skipped, showNewOnly, hideSkipped]
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

  const togglePost = useCallback(
    (post: PostWithScan, mediaFilter: "all" | "image" | "video" | "album" = "all") => {
      const ids = visibleMedia(post, mediaFilter)
        .filter(
          (item) =>
            (!showNewOnly || !isItemHandled(item, downloaded, skipped)) &&
            (!hideSkipped || !isItemSkipped(item, skipped))
        )
        .map((item) => item.id);
      setSelected((prev) => {
        const allSelected = ids.length > 0 && ids.every((id) => prev.has(id));
        const next = new Set(prev);
        for (const id of ids) {
          if (allSelected) next.delete(id);
          else next.add(id);
        }
        return next;
      });
    },
    [downloaded, skipped, showNewOnly, hideSkipped]
  );

  const selectAllVisible = useCallback(
    () =>
      setSelected(
        new Set(
          visibleItems
            .filter((item) => !isItemSkipped(item, skipped))
            .map((item) => item.id)
        )
      ),
    [visibleItems, skipped]
  );

  const selectOnlyNew = useCallback(
    () =>
      setSelected(
        new Set(
          visibleItems
            .filter((item) => !isItemHandled(item, downloaded, skipped))
            .map((item) => item.id)
        )
      ),
    [visibleItems, downloaded, skipped]
  );

  const clearSelection = useCallback(() => setSelected(new Set()), []);

  const selectByType = useCallback(
    (type: "image" | "video") =>
      setSelected(
        new Set(
          visibleItems
            .filter((item) => item.media_type === type && !isItemSkipped(item, skipped))
            .map((item) => item.id)
        )
      ),
    [visibleItems, skipped]
  );

  const selectAlbums = useCallback(
    () =>
      setSelected(
        new Set(
          visiblePosts
            .filter((post) => post.media_items.length > 1)
            .flatMap((post) => visibleMedia(post, filter))
            .filter((item) => !isItemSkipped(item, skipped))
            .map((item) => item.id)
        )
      ),
    [visiblePosts, filter, skipped]
  );

  const invertSelection = useCallback(
    () =>
      setSelected(
        new Set(
          visibleItems
            .filter((item) => !selected.has(item.id) && !isItemSkipped(item, skipped))
            .map((item) => item.id)
        )
      ),
    [selected, visibleItems, skipped]
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
