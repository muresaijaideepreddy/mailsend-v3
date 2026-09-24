from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Message, Attachment, Workspace, SenderAccount
from .services import parse_addresses, validate_attachments, bcc_from_csv


class MessageForm(forms.ModelForm):
    version = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    body = forms.CharField(max_length=100_000, label='Message', widget=forms.Textarea(attrs={'rows': 12}))
    attachment_1 = forms.FileField(required=False)
    attachment_2 = forms.FileField(required=False)
    attachment_3 = forms.FileField(required=False)
    remove_attachments = forms.ModelMultipleChoiceField(queryset=Attachment.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    bcc_csv = forms.FileField(required=False, label='Import BCC from CSV')

    class Meta:
        model = Message
        fields = ['sender', 'to', 'cc', 'bcc', 'subject', 'body', 'send_date']
        widgets = {'to': forms.TextInput(attrs={'placeholder': 'recipient@example.com'}), 'cc': forms.TextInput(), 'bcc': forms.TextInput(), 'send_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'), 'body': forms.Textarea(attrs={'rows': 12}), 'subject': forms.TextInput(attrs={'placeholder': 'Give your message a subject'})}
        labels = {'to': 'To', 'cc': 'CC', 'bcc': 'BCC', 'send_date': 'Send date', 'body': 'Message'}
        help_texts = {'to': 'Separate multiple email addresses with commas.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sender'].queryset = SenderAccount.objects.filter(workspace_id=self.instance.workspace_id, connected=True)
        self.fields['sender'].label = 'From'
        self.fields['sender'].empty_label = 'Primary account' + (f' — {self.instance.workspace.executive.email}' if self.instance.workspace_id else '')
        self.fields['version'].initial = self.instance.version or 1
        for name in ('to', 'subject', 'body', 'send_date'):
            self.fields[name].required = not bool(self.instance.imported_from)
        if self.instance.pk:
            self.fields['remove_attachments'].queryset = self.instance.attachments.all()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean(self):
        data = super().clean()
        if data.get('bcc_csv'):
            try:
                imported = bcc_from_csv(data['bcc_csv'])
                data['bcc'] = parse_addresses(','.join(filter(None, [data.get('bcc', ''), imported])))
            except ValidationError as exc:
                self.add_error('bcc_csv', exc)
        files = [data[f'attachment_{i}'] for i in range(1, 4) if data.get(f'attachment_{i}')]
        existing = self.instance.attachments.exclude(pk__in=[a.pk for a in data.get('remove_attachments', [])]) if self.instance.pk else []
        try:
            validate_attachments(files, existing=existing)
        except ValidationError as exc:
            self.add_error(None, exc)
        self.new_files = files
        return data


class SignatureForm(forms.ModelForm):
    class Meta:
        model = Workspace
        fields = ['signature']
        widgets = {'signature': forms.Textarea(attrs={'rows': 9, 'class': 'form-control', 'maxlength': 10000})}
    def clean_signature(self):
        value = self.cleaned_data['signature']
        if len(value) > 10000:
            raise ValidationError('Keep your signature under 10,000 characters.')
        return value


class AssistantForm(forms.Form):
    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150, required=False, label='Name')
    password = forms.CharField(widget=forms.PasswordInput, label='Temporary password')

    def clean_username(self):
        value = self.cleaned_data['username'].strip()
        get_user_model()._meta.get_field('username').run_validators(value)
        if get_user_model().objects.filter(username__iexact=value).exists():
            raise ValidationError('This username is already in use.')
        if get_user_model().objects.filter(email__iexact=value).exists():
            raise ValidationError('This username matches an existing account email. Choose another username.')
        return value

    def clean(self):
        data = super().clean()
        if data.get('password'):
            user = get_user_model()(username=data.get('username', ''), first_name=data.get('first_name', ''))
            try:
                validate_password(data['password'], user=user)
            except ValidationError as exc:
                self.add_error('password', exc)
        return data


class MergeForm(forms.Form):
    sender = forms.ModelChoiceField(queryset=SenderAccount.objects.none(), required=False, label='From')

    def __init__(self, *args, workspace=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sender'].queryset = SenderAccount.objects.filter(workspace=workspace, connected=True)
        self.fields['sender'].empty_label = f'Primary account — {workspace.executive.email}' if workspace else 'Primary account'

    csv_file = forms.FileField(label='CSV file')
    subject = forms.CharField(max_length=255)
    body = forms.CharField(max_length=100_000, widget=forms.Textarea(attrs={'rows': 10}))
    cc = forms.CharField(required=False)
    bcc = forms.CharField(required=False)
    send_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    # merge_preview validates every expanded address, after substituting CSV
    # placeholders. Validating the template itself would reject {{cc_email}}.


class DocumentImportForm(forms.Form):
    document = forms.FileField(label='Word document or PDF', widget=forms.ClearableFileInput(attrs={'accept': '.docx,.pdf'}))
    token = forms.CharField(widget=forms.HiddenInput)
