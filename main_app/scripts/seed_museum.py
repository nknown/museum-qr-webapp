from wagtail.models import Page
from main_app.models import Exposition, Piece, Slide
from django.contrib.auth import get_user_model

User = get_user_model()

def run():
    # get or create admin user
    user, _ = User.objects.get_or_create(username="admin")

    # get root page
    root = Page.get_first_root_node()

    # create exposition
    exposition = Exposition(
        title="Demo Exposition",
        description="A sample exposition for demonstration"
    )
    root.add_child(instance=exposition)
    exposition.save_revision()
    if exposition.live:
        exposition.unpublish()

    # create pieces
    for i in range(1, 4):
        piece = Piece(
            title=f"Piece {i}",
            author="Unknown Artist",
            period="Renaissance",
            description=f"Description for piece {i}"
        )
        exposition.add_child(instance=piece)
        piece.save_revision()
        if piece.live:
            piece.unpublish()

        # create slides
        for j in range(1, 4):
            Slide.objects.create(
                parent_piece=piece,
                title=f"Slide {j} for Piece {i}",
                body=[
                    ("heading", f"Slide {j}"),
                    ("paragraph", f"This is slide {j} content for piece {i}.")
                ]
            )

    print("✅ Demo museum data created successfully!")
