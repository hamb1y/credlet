// Disposable native GTK application for accessibility integration acceptance.
#include <gtk/gtk.h>
#include <gdk/gdkx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <string.h>
static GtkWidget *window, *username, *password, *code;
static gboolean input(GIOChannel *channel, GIOCondition condition, gpointer unused) {
    gchar *line = NULL;
    if (g_io_channel_read_line(channel, &line, NULL, NULL, NULL) != G_IO_STATUS_NORMAL) { gtk_main_quit(); return FALSE; }
    g_strchomp(line);
    GtkWidget *field = !strcmp(line,"focus-user") ? username : !strcmp(line,"focus-password") ? password : !strcmp(line,"focus-code") ? code : NULL;
    if (field) {
        gtk_widget_grab_focus(field);
        Display *display = GDK_DISPLAY_XDISPLAY(gdk_display_get_default());
        XSetInputFocus(display,GDK_WINDOW_XID(gtk_widget_get_window(window)),RevertToParent,CurrentTime);XFlush(display);
        printf("focused\n");fflush(stdout);
    } else if (!strcmp(line,"inspect")) {
        // Test-only process output, not product logging.
        printf("%s\t%s\t%s\n",gtk_entry_get_text(GTK_ENTRY(username)),gtk_entry_get_text(GTK_ENTRY(password)),gtk_entry_get_text(GTK_ENTRY(code)));fflush(stdout);
    } else if (!strcmp(line,"hide")) { gtk_widget_hide(password);printf("hidden\n");fflush(stdout); }
    else if (!strcmp(line,"show")) { gtk_widget_show(password);printf("shown\n");fflush(stdout); }
    else if (!strcmp(line,"disable")) { gtk_widget_set_sensitive(password,FALSE);printf("disabled\n");fflush(stdout); }
    else if (!strcmp(line,"enable")) { gtk_widget_set_sensitive(password,TRUE);printf("enabled\n");fflush(stdout); }
    else if (!strcmp(line,"readonly")) { gtk_editable_set_editable(GTK_EDITABLE(password),FALSE);printf("readonly\n");fflush(stdout); }
    else if (!strcmp(line,"quit")) gtk_main_quit();
    g_free(line);return TRUE;
}
int main(int argc, char **argv) {
    gtk_init(&argc,&argv);g_set_application_name("Lockbox native fixture");
    window=gtk_window_new(GTK_WINDOW_TOPLEVEL);gtk_window_set_title(GTK_WINDOW(window),"Lockbox native fixture");
    GtkWidget *box=gtk_box_new(GTK_ORIENTATION_VERTICAL,10);gtk_container_add(GTK_CONTAINER(window),box);
    username=gtk_entry_new();password=gtk_entry_new();code=gtk_entry_new();gtk_entry_set_visibility(GTK_ENTRY(password),FALSE);
    gtk_entry_set_placeholder_text(GTK_ENTRY(username),"Username");gtk_entry_set_placeholder_text(GTK_ENTRY(password),"Password");gtk_entry_set_placeholder_text(GTK_ENTRY(code),"Authenticator code");
    gtk_box_pack_start(GTK_BOX(box),username,FALSE,FALSE,0);gtk_box_pack_start(GTK_BOX(box),password,FALSE,FALSE,0);gtk_box_pack_start(GTK_BOX(box),code,FALSE,FALSE,0);
    gtk_widget_show_all(window);
    GIOChannel *stdin_channel=g_io_channel_unix_new(0);g_io_add_watch(stdin_channel,G_IO_IN|G_IO_HUP,input,NULL);
    printf("ready\n");fflush(stdout);gtk_main();return 0;
}
