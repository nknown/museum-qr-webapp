from wagtail import blocks
from wagtail.images.blocks import ImageChooserBlock
from wagtail.documents.blocks import DocumentChooserBlock
from wagtail.embeds.blocks import EmbedBlock


class QuestionBlock(blocks.StructBlock):
    question = blocks.CharBlock()
    answer = blocks.RichTextBlock()

    class Meta:
        template = 'main_app/blocks/question.html'
        icon = 'help'
        label = 'Interactive question'


class PresentationBlocks(blocks.StreamBlock):
    text = blocks.RichTextBlock()
    image = ImageChooserBlock(template='main_app/blocks/image.html')
    video = EmbedBlock(label='Video URL')
    document = DocumentChooserBlock(template='main_app/blocks/document.html')
    question = QuestionBlock()
