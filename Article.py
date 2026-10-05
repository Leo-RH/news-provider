class Article:
    def __init__(self, title, desc, date, link, topic, image, source, source_name=""):
        self.title = title
        self.desc = desc
        self.date = date
        self.link = link
        self.topic = topic
        self.image = image
        self.source = source
        self.source_name = source_name or source

    @property
    def is_valid(self):
        """An article is worth keeping if it has at least a title or a link."""
        return bool(self.title or self.link)

    @property
    def dedup_key(self):
        """Identity used to drop duplicates across pages/paths."""
        return (self.link or self.title or "").strip().lower()

    def to_dict(self):
        return {
            "title": self.title,
            "description": self.desc,
            "date": self.date,
            "link": self.link,
            "topic": self.topic,
            "image": self.image,
            "source": self.source,
            "source_name": self.source_name,
        }

    def show(self):
        print("Title: " + self.title)
        print("Description: " + self.desc)
        print("Date: " + self.date)
        print("Link: " + self.link)
        print("Topic: " + self.topic)
        print("Image: " + self.image)
