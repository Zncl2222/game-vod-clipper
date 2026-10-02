import unittest
from pathlib import Path


class SkillMetadataTest(unittest.TestCase):
    def setUp(self):
        self.skill_path = Path("skills/game-vod-boss-clipper/SKILL.md")
        self.content = self.skill_path.read_text(encoding="utf-8")

    def test_skill_file_exists(self):
        self.assertTrue(self.skill_path.is_file())

    def test_frontmatter_contains_required_metadata(self):
        self.assertTrue(self.content.startswith("---\n"))
        self.assertIn("name: game-vod-boss-clipper", self.content)
        self.assertIn("description:", self.content)
        self.assertIn("compatibility:", self.content)

    def test_skill_preserves_clipping_safety_rules(self):
        required_phrases = [
            "Do not include earlier failed attempts",
            "5-10 seconds after",
            "trusted source",
            "game-vod-clipper clip",
            "Validate The Result",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.content)


if __name__ == "__main__":
    unittest.main()
